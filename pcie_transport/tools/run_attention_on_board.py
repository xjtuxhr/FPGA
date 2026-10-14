"""Board-side single-layer ATTENTION runner (framed v2). Fail-closed.

Drives the real v2 transport for ``ATTENTION``(op=0): one RESET_CACHE, then N
serial ATTENTION requests (Q/K/V -> attention output). Frames are validated by
``Transport.round_trip`` (seq/layer/position/op, CRC, length); if a golden JSON
is supplied the returned output[576] is compared against PC1's reference.

Requirements:
  --binding <json>   complete kind=real binding (TRANSPORT_BINDING.md)
  --device  <module> python module exposing make_device(binding) -> DeviceOps
                     (default: pcie_transport.sgdma_device)

Fail-closed: refuses without a complete real binding; never appends KV on
error, never falls back to CPU. The endpoint MUST have a working
``ATTENTION(op=0)`` path (currently unimplemented -- this runner is ready for
the day B lands it; until then a run will FAULT and report RUN_FAILED).

CAVEAT: after a JTAG FPGA reconfiguration the PCIe link can look "up" in
``lspci`` while the endpoint is stale; perform the full recovery
(rmmod anlogic_pci + unbind rk-pcie + pcie1-fpga.sh + insmod) first.
"""
import argparse
import importlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from pcie_contract import contract as c
from pcie_transport.attention_vectors import (
    build_pattern_qkv, pack_qkv, load_golden, compare_output,
)
from pcie_transport.binding import Binding, BindingError
from pcie_transport.transport import Transport, TransportError

DEFAULT_DEVICE = "pcie_transport.sgdma_device"


def load_device(module_path: str, binding: Binding):
    mod = importlib.import_module(module_path)
    maker = getattr(mod, "make_device", None)
    if maker is None:
        raise RuntimeError(f"{module_path} has no make_device(binding)")
    return maker(binding)


def build_cases(rounds: int, layer: int, start_position: int, golden_path):
    """Return a list of {layer, position, q, k, v, output?} cases."""
    if golden_path is not None:
        return load_golden(golden_path)
    cases = []
    for i in range(rounds):
        position = start_position + i
        q, k, v = build_pattern_qkv(position)
        cases.append({"layer": layer, "position": position, "q": q, "k": k, "v": v})
    return cases


def summarize(totals, framing_ok, compared, matched, max_abs, nonfinite, profile):
    out = {
        "rounds": len(totals),
        "errors": 0,
        "framing_ok": framing_ok,
        "compared": compared,
        "matched": matched,
        "nonfinite_outputs": nonfinite,
        "profile": profile,
    }
    if compared:
        out["max_abs"] = max_abs
    if totals:
        s = sorted(totals)
        out.update({
            "min_s": s[0], "mean_s": statistics.mean(s), "max_s": s[-1],
            "p50_s": s[max(0, int(round(0.50 * (len(s) - 1))))],
            "p95_s": s[max(0, int(round(0.95 * (len(s) - 1))))],
            "total_s": sum(s),
        })
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Board-side single-layer ATTENTION runner (framed v2)")
    parser.add_argument("--binding", type=Path, required=True, help="complete kind=real binding JSON")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="module exposing make_device(binding)")
    parser.add_argument("--layer", type=int, default=0, help="layer for pattern runs (golden uses its own)")
    parser.add_argument("--start-position", type=int, default=0)
    parser.add_argument("--rounds", type=int, default=1, help="pattern runs only; golden length wins")
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--golden", type=Path, default=None, help="PC1 golden JSON (enables output compare)")
    parser.add_argument("--out", type=Path, default=None, help="directory for JSON/CSV evidence")
    parser.add_argument("--check", action="store_true", help="validate binding + device import only, run nothing")
    args = parser.parse_args(argv)

    try:
        binding = Binding.load(args.binding)
    except BindingError as exc:
        print(f"BINDING_FAILED: {exc}", file=sys.stderr)
        return 1
    if binding.kind != "real":
        print("RUN_REFUSED: board runner requires a kind=real binding", file=sys.stderr)
        return 1

    try:
        device = load_device(args.device, binding)
    except Exception as exc:  # import error / missing hook
        print(f"DEVICE_LOAD_FAILED: {exc}", file=sys.stderr)
        return 1

    if args.check:
        print(f"CHECK_OK: binding v{binding.binding_version} complete; device module {args.device} loaded")
        return 0

    try:
        cases = build_cases(args.rounds, args.layer, args.start_position, args.golden)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"CASES_FAILED: {exc}", file=sys.stderr)
        return 2
    if args.rounds < 1 and args.golden is None:
        print("Pattern runs need --rounds >= 1.", file=sys.stderr)
        return 2

    transport = Transport(device, binding)
    totals, framing_ok, compared, matched, nonfinite = [], 0, 0, 0, 0
    max_abs = 0.0
    try:
        transport.reset_cache(timeout_s=args.timeout_s)
        for case in cases:
            payload = pack_qkv(case["q"], case["k"], case["v"])
            response, timing = transport.round_trip(
                c.OP_ATTENTION, case["layer"], case["position"], payload,
                timeout_s=args.timeout_s)
            framing_ok += 1
            totals.append(timing.total_s)
            if "output" in case:
                result = compare_output(response, case["output"])
                compared += 1
                if result.get("nonfinite"):
                    nonfinite += 1
                elif result["match"]:
                    matched += 1
                max_abs = max(max_abs, result["max_abs"])
    except (TransportError, NotImplementedError) as exc:
        print(f"RUN_FAILED after {framing_ok}/{len(cases)} frames: {exc}", file=sys.stderr)
        return 1

    summary = summarize(totals, framing_ok, compared, matched, max_abs, nonfinite,
                        "framed_v2 ATTENTION (1952B/1184B logical frames)")
    summary.update({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "backend": "board",
        "device": args.device,
        "binding_version": binding.binding_version,
        "contract_version": c.PROTOCOL_VERSION,
        "golden": str(args.golden) if args.golden else None,
        "note": "ATTENTION executes on the endpoint; framing via Transport; compare only if golden given",
    })
    print(json.dumps(summary, indent=2))
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "attention_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        with (args.out / "attention_rounds.csv").open("w", encoding="utf-8", newline="") as f:
            f.write("idx,layer,position,total_s\n")
            for idx, case in enumerate(cases):
                if idx < len(totals):
                    f.write(f"{idx},{case['layer']},{case['position']},{totals[idx]:.9f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

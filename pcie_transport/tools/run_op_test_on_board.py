"""Board-side OP_TEST runner (framed v2). Fail-closed.

Runs N serial request/response rounds against a REAL binding using the v2
transport state machine and contract codec. This is the intended way to produce
board OP_TEST evidence; PC mock runs stay in oracle_test.py.

Requirements:
  --binding <json>   complete kind=real binding (TRANSPORT_BINDING.md)
  --device  <module> python module exposing make_device(binding) -> DeviceOps
                     (default: pcie_transport.sgdma_device, filled post-enumeration)

Fail-closed: refuses without a complete real binding; if the device adapter is
not yet implemented (post-enumeration TODO) the run fails with RUN_FAILED
instead of fabricating results. Never appends KV, never falls back to CPU.
"""
import argparse
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from pcie_contract import contract as c
from pcie_transport.binding import Binding, BindingError
from pcie_transport.transport import Transport, TransportError
from pcie_transport.oracle_test import run_rounds, summarize

DEFAULT_DEVICE = "pcie_transport.sgdma_device"


def load_device(module_path: str, binding: Binding):
    mod = importlib.import_module(module_path)
    maker = getattr(mod, "make_device", None)
    if maker is None:
        raise RuntimeError(f"{module_path} has no make_device(binding)")
    return maker(binding)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Board-side OP_TEST 30-round runner (framed v2)")
    parser.add_argument("--binding", type=Path, required=True, help="complete kind=real binding JSON")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="module exposing make_device(binding)")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--out", type=Path, default=None, help="directory for JSON/CSV evidence")
    parser.add_argument("--check", action="store_true",
                        help="validate binding + device import only, run nothing")
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

    if args.rounds < 30:
        print("At least 30 rounds are required for the minimum stability gate.", file=sys.stderr)
        return 2

    transport = Transport(device, binding)
    try:
        reset, records = run_rounds(transport, args.rounds, args.timeout_s)
    except (TransportError, NotImplementedError) as exc:
        print(f"RUN_FAILED: {exc}", file=sys.stderr)
        return 1

    summary = summarize(records)
    summary.update({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "backend": "board",
        "device": args.device,
        "binding_version": binding.binding_version,
        "contract_version": c.PROTOCOL_VERSION,
        "reset_timing_s": reset.total_s,
        "note": "BOARD framed v2 (1952B/1184B logical frames); raw profile reported separately",
    })
    print(json.dumps(summary, indent=2))
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "op_test_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        with (args.out / "op_test_rounds.csv").open("w", encoding="utf-8", newline="") as f:
            f.write("counter,submit_s,wait_s,readback_s,verify_s,total_s\n")
            for r in records:
                t = r["timing"]
                f.write(f"{r['counter']},{t.submit_s:.9f},{t.wait_s:.9f},{t.readback_s:.9f},{t.verify_s:.9f},{t.total_s:.9f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

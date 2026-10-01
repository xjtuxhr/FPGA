"""OP_TEST 30-round serial benchmark against a transport backend.

PC mock runs verify the state machine and verification logic only; they are
NOT board Gate evidence and never claim hardware latency. Board runs require
a complete binding (--binding path) and human-performed board experiment per
COOPERATION.md; results are then marked framed/raw and archived.

v2 TEST oracle: first 4 payload bytes are a little-endian counter,
byte[i] = (counter + i) & 255 for i >= 4; the endpoint returns the first
c2h_bytes of the request payload without executing Attention or KV writes.
"""
import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pcie_contract import contract as c
from pcie_transport.transport import Transport, TransportError, RoundTiming
from pcie_transport.tests.mock_device import MockDevice


def make_binding_for_mock() -> object:
    from pcie_transport.binding import Binding
    return Binding(
        binding_version=1, contract_version=2, evidence_ref="mock (PC-only, not board evidence)",
        bdf="mock:00.0", vendor_device="1edb:abcd", bound_driver="mock",
        h2c_node="/dev/mock_h2c", c2h_node="/dev/mock_c2h", control_node="/dev/mock_ctrl",
        access_method="mock in-memory", data_mode="mock",
        dma_alignment="1", dma_length_granularity="1", submit_order="mock",
        dma_completion="mock", attention_completion="mock", timeout_handling="finite monotonic deadline",
        clock_method="time.monotonic (PC only)",
    )


def run_rounds(transport: Transport, rounds: int, timeout_s: float):
    reset = transport.reset_cache(timeout_s=timeout_s)
    records = []
    for i in range(rounds):
        counter = i + 1
        payload = c.make_test_payload(counter)
        response, timing = transport.round_trip(c.OP_TEST, i % c.LAYERS, i % c.CONTEXT,
                                                payload, timeout_s=timeout_s)
        expected = c.test_response_payload(payload)
        # Transport already verified CRC/seq/op/layer/position; byte-compare
        # the oracle payload returned by the endpoint as well.
        if response[c.HEADER_BYTES:] != expected:
            raise TransportError(f"Oracle payload mismatch on counter {counter}")
        records.append({"counter": counter, "timing": timing})
    return reset, records


def summarize(records):
    totals = [r["timing"].total_s for r in records]
    out = {
        "rounds": len(records),
        "errors": 0,
        "profile": "framed_v2 (1952B/1184B logical frames; mock has no DMA padding)",
        "min_s": min(totals), "mean_s": statistics.mean(totals),
        "max_s": max(totals),
        "p95_s": sorted(totals)[max(0, int(len(totals) * 0.95) - 1)],
        "total_s": sum(totals),
        "note": "PC mock only; NOT board latency evidence",
    }
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="OP_TEST 30-round serial benchmark")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument("--timeout-s", type=float, default=5.0)
    parser.add_argument("--mock", action="store_true", help="run against in-memory mock (PC only)")
    parser.add_argument("--binding", type=Path, default=None,
                        help="binding evidence JSON (board runs only; requires human experiment)")
    parser.add_argument("--out", type=Path, default=None, help="directory for JSON/CSV artifacts")
    args = parser.parse_args(argv)

    if args.rounds < 30:
        print("At least 30 rounds are required for the minimum stability gate.", file=sys.stderr)
        return 2
    if args.mock and args.binding:
        print("--mock and --binding are mutually exclusive", file=sys.stderr)
        return 2

    if args.mock:
        binding = make_binding_for_mock()
        device = MockDevice()
        label = "mock"
    else:
        print("Board runs are not implemented here: fill TRANSPORT_BINDING.md evidence first.", file=sys.stderr)
        return 2

    transport = Transport(device, binding)
    try:
        reset, records = run_rounds(transport, args.rounds, args.timeout_s)
    except TransportError as exc:
        print(f"RUN_FAILED: {exc}", file=sys.stderr)
        return 1

    summary = summarize(records)
    summary.update({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "backend": label,
        "contract_version": c.PROTOCOL_VERSION,
        "reset_timing_s": reset.total_s,
    })
    print(json.dumps(summary, indent=2))
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "oracle_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        with (args.out / "oracle_rounds.csv").open("w", encoding="utf-8", newline="") as f:
            f.write("counter,submit_s,wait_s,readback_s,verify_s,total_s\n")
            for r in records:
                t = r["timing"]
                f.write(f"{r['counter']},{t.submit_s:.9f},{t.wait_s:.9f},{t.readback_s:.9f},{t.verify_s:.9f},{t.total_s:.9f}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

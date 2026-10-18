# PC2 status adapter (B mode) - 2026-10-18

Host-side adapter for the proposed `READY / FAULT / DONE / SOFT_RESET`
interface. It is ready for B/PC1 review and for the real register offsets to be
filled in. **It does not claim a hard H2C write deadline.**

## What it does

- `MockStatus` + `StatusTransport`: offline tests for READY gating, DONE/ERR,
  FAULT, soft reset, and two sessions.
- `RealBarStatus`: 4-byte BAR access using the verified paths:
  - BAR0 via `/dev/ANLOGIC-PCI0_user` (node pread/pwrite)
  - BAR1 via `/dev/ANLOGIC-PCI0_control`
  - or `ANLOGIC_IOCR` / `ANLOGIC_IOCW` with `bar_id=0/1`
- `probe_bar0(offset)`: read-only path check; does not interpret the value as
  status.
- `StatusTransport`: wraps the existing `SgdmaDevice`/`DeviceOps`:
  - before write: poll READY; if not ready, fail fast without H2C
  - after write: poll DONE/ERR/FAULT
  - `soft_reset()` writes CONTROL.SOFT_RESET and waits for READY
  - `deadline_enforced` delegates to the inner device (must stay False)

## What it does NOT do

- It does not make a blocked `os.write` cancellable. READY pre-poll only
  covers the pre-write state; the in-flight abort test is still required.
- It does not guess register offsets. `RealBarStatus` refuses if
  `status_offset` or `control_offset` is `None`.
- It does not flip `deadline_enforced` or `session_reusable` to true.
- It does not reset the FPGA endpoint by itself; `SOFT_RESET` is a proposed
  RTL register and must be implemented by B.

## Verified host path (2026-10-18, read-only)

```text
/dev/ANLOGIC-PCI0_control + pread(4B, off) -> BAR1
/dev/ANLOGIC-PCI0_user    + pread(4B, off) -> BAR0
ANLOGIC_IOCR bar_id=0/1                    -> BAR0/BAR1

BAR0 0x5C = 0x56440013
BAR0 0x74 = 0x00000c01
BAR0 0x84 = 0x00002001
```

These values are existing registers, not the new status. The new offsets are
still TBD by B.

## Integration

1. B confirms `bar_id`, `status_offset`, `control_offset`, bit semantics, and
   read/write side effects.
2. PC2 constructs:

```python
status = RealBarStatus(
    bar_id=...,              # 0=BAR0, 1=BAR1
    status_offset=...,       # 4-byte aligned
    control_offset=...,      # 4-byte aligned
)
transport = StatusTransport(inner_sgdma_transport, status)
```

3. PC1 reviews `DONE`/`seq`/`layer`/`position` semantics and the FAULT policy.
4. Run the mock tests and the board read-only probe; then the negative tests
   (pre-write not READY, in-flight block, two independent H2C processes).

## Offline tests

```bash
python -B test_status_adapter.py
```

On the board, a read-only path check:

```bash
python3 -B -c "import status_adapter as s; print(hex(s.probe_bar0(0x5c)))"
```

Expected on the current bit: `0x56440013` (path check only).

## Files

- `status_adapter.py`
- `test_status_adapter.py`
- `README.md`

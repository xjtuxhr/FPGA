DEST=/home/kvdev/work_pc2_pcie/pc2_consistent_20261016
PYTHONPATH="$DEST" python3 - <<'PY'
import fcntl
import os
import sys
import threading
import time

DEST = "/home/kvdev/work_pc2_pcie/pc2_consistent_20261016"
sys.path.insert(0, DEST)
from pcie_contract import contract as c

H2C = "/dev/ANLOGIC-PCI0_h2c_0"
ANLOGIC_IOCABORT = (0 << 30) | (0 << 16) | (ord('x') << 8) | 11
FRAMES = [c.pack_request(5000 + i, 0, 0, c.make_test_payload(i + 1), op=c.OP_TEST)
          for i in range(12)]
progress = []
result = {}


def worker():
    fd = os.open(H2C, os.O_WRONLY)
    try:
        for i, frame in enumerate(FRAMES):
            t0 = time.monotonic()
            n = os.write(fd, frame)
            progress.append((i, n, time.monotonic() - t0))
    except BaseException as exc:
        result["err"] = (type(exc).__name__, str(exc))
    finally:
        os.close(fd)


th = threading.Thread(target=worker)
th.start()
start = time.monotonic()
last_count = 0
last_change = start
aborted = False
abort_elapsed = None
while time.monotonic() - start < 12:
    time.sleep(0.1)
    if len(progress) != last_count:
        last_count = len(progress)
        last_change = time.monotonic()
    if not th.is_alive():
        break
    if time.monotonic() - last_change > 1.0:
        print("STALL after %d writes" % len(progress), flush=True)
        try:
            fd2 = os.open(H2C, os.O_RDWR)
        except OSError:
            fd2 = os.open(H2C, os.O_WRONLY)
        t0 = time.monotonic()
        try:
            fcntl.ioctl(fd2, ANLOGIC_IOCABORT)
            print("ABORT_IOCTL_OK", flush=True)
            aborted = True
        except BaseException as exc:
            print("ABORT_IOCTL_ERR %s %s" % (type(exc).__name__, exc), flush=True)
        finally:
            os.close(fd2)
        th.join(timeout=5.0)
        abort_elapsed = time.monotonic() - t0
        break

if th.is_alive():
    th.join(timeout=1.0)
print("progress_count=%d last=%r" % (len(progress), progress[-1] if progress else None), flush=True)
print("worker_alive=%s aborted=%s abort_elapsed=%.3f" % (th.is_alive(), aborted,
      -1.0 if abort_elapsed is None else abort_elapsed), flush=True)
print("result=%r" % (result.get("err"),), flush=True)
PY

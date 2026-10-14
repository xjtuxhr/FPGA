# 实板验证清单：H2C 有界写（申请独占窗口时使用）

状态：**已执行（2026-10-14）——结果 NEGATIVE：deadline 未生效。** 作者：PC2。
目标：证明 H2C `os.write` 能在**我们的 deadline** 被中断（而非等到驱动 `h2c_timeout`=10s），且超时后需 RESET 恢复。**不改驱动/系统。**

## 0. 结果（2026-10-14 板测）

| 步骤 | 结果 |
|---|---|
| 正常路径回归（Transport，30 轮 OP_TEST） | ✅ OK=30 bad=0，p50≈0.33 ms；`deadline_enforced` 属性此时返回 True |
| 制造阻塞（发 1 个未实现的 `ATTENTION` 帧 → 端点停止消费） | ✅ 下一帧 H2C 写确实阻塞 |
| 断言：小 deadline 被中断 | ❌ **未通过**：写返回于 **10.000 s**（= 驱动 `h2c_timeout`），**不是** 0.5 s；dmesg 见驱动自身 `xfer … timed out` |
| 断言：超时后需 RESET | ✅ 之后普通 `reset_cache` 立即 FAULT，需完整恢复（rmmod+unbind+PERST+insmod）后才能再用 |
| 恢复后 | ✅ 30 轮 OP_TEST 再次 OK=30 bad=0 |

**结论**：SIGALRM 机制在本板**没有**把写收紧到我们的 deadline；`_Deadline` 直到内核调用在驱动超时后返回才触发。
因此 `metadata().deadline_enforced` 必须保持 **False**（已修：`SgdmaDevice.deadline_enforced` 现在要求
`deadline_verified=True` 显式确认，默认 False）。**不用"外层 Python timeout"冒充已解决。**

复现命令（独占窗口，允许写端点状态；结束须完整恢复）：

```bash
DEST=/home/kvdev/work_pc2_pcie/h2cdeadline_20260427_211835
python3 "$DEST/h2c_test.py" "$DEST" regress    # 30 轮回归（先做）
python3 "$DEST/h2c_test.py" "$DEST" block      # poison ATTENTION + 0.5s deadline 断言
# 恢复：systemctl stop anlogic-sgdma; rmmod anlogic_pci; unbind; /usr/local/sbin/pcie1-fpga.sh; insmod
```

---

## 0. 前置

- PCIe link up、`1edb:abcd` 枚举、`/dev/ANLOGIC-PCI0_*` 齐全（否则先跑加固版 `/usr/local/sbin/pcie1-fpga.sh`）。
- 把最新 `pcie_transport/`（含带 `_interruptible_deadline` 的 `sgdma_device.py`）解到 `/home/kvdev/optest_v2/`。
- 记录：`cat /sys/module/anlogic_pci/parameters/h2c_timeout`（预期 10）、bitstream sha256、commit。

## 1. 正常路径回归（先证明无副作用）

```bash
cd /home/kvdev/optest_v2
PYTHONPATH=. python3 -m pcie_transport.tools.run_op_test_on_board \
    --binding pcie_transport/bindings/board_20261011.json --rounds 30 --timeout-s 5.0
```
预期：`errors=0`，与既有 30 轮结果一致；单次写耗时应为亚毫秒级。

## 2. 制造会阻塞的 H2C 写

思路：让 endpoint **不消费/不完成**，使 SGDMA rx FIFO 填满后 `os.write` 阻塞。
- 已知本 bit 对 **未知 op（如 op=3）或 ATTENTION** 会走进 S_PAY/S_TXP 并从空 FIFO 读 → 挂死（见
  `PC2_REVIEW_v2_ENDPOINT_RTL.md` F4）。
- 步骤：连续快速写 2–3 个「未知 op」帧（或一个远超 FIFO 的大写），使 rx FIFO 灌满、后续写阻塞。

## 3. 断言：小 deadline 处被中断

用小脚本经 `SgdmaDevice.write(frame, deadline=now+0.5)` 发起会阻塞的写：
- 预期：**在 ≈0.5s** 返回并抛 `TransportError`（"aborted at deadline"），**而非 10s**。
- 记录实际返回时间、`dmesg | tail`（应见 driver 的 `timed out` / `-ERESTARTSYS` 相关行）。
- 判据：返回时间 ∈ [0.4s, 1.0s]，且 < 5s（远小于驱动 10s）。

```python
# 示意
from pcie_transport.binding import Binding; from pcie_transport.sgdma_device import SgdmaDevice
from pcie_contract import contract as c
import time
dev = SgdmaDevice(Binding.load("pcie_transport/bindings/board_20261011.json"))
bad = c.pack_request(1, 0, 0, b"\x00"*1920, op=3)          # 未知 op -> endpoint 挂死
t0 = time.monotonic()
try:
    dev.write(bad, deadline=time.monotonic()+0.5)           # 第二次写会阻塞
except Exception as e:
    print("aborted after", time.monotonic()-t0, type(e).__name__, e)
```

## 4. 断言：超时后需 RESET 恢复

- 步骤 3 之后，直接发正常 `OP_TEST` → 预期失败/超时（引擎已被驱动停掉）。
- 再走一次 **RESET/recover**（重跑 `pcie1-fpga.sh` 或 `Transport.recover()` + `reset_cache()`），
  确认恢复后正常帧通过。

## 5. 记录与结论

- 命令、deadline、实测返回时间、`h2c_timeout` 值、`dmesg`、恢复步骤与结果。
- 结论写清：写是否**在 deadline 处被中断**（是/否），以及**是否必须 RESET 才能复用**。
- 通过后：`metadata().deadline_enforced` 可置真（配合 PC1 桥接 F1 改动），实板探针方可放行。

## 6. 边界

- 本清单**不改驱动/系统**；若步骤 2 无法在不破坏状态的前提下制造阻塞，如实记录并另议，
  不用"外层 Python timeout"冒充已解决。
- 失败即停，保留完整 stdout/`dmesg`，不做自动重试。

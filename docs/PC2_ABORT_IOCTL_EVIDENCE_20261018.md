# PC2 in-flight H2C abort evidence (2026-10-18)

- 状态：**驱动中止路径已实板验证；不是硬 deadline，跨进程复用仍需 RTL 软复位**
- 板卡：`linaro-alip`，kernel `6.1.99`，endpoint `1edb:abcd`
- 临时驱动：`/home/kvdev/sgdma_drv_fix/anlogic_pci.ko`
- 原始驱动：已恢复 `/lib/modules/6.1.99/extra/anlogic_pci.ko`（SHA256 `fb04231e…1007e`）
- 板卡状态：已 recovery，自恢复后未发 H2C

## 1. 驱动补丁

在 vendor `anlogic_pci` 源码副本上增加：

- `cdev_ctrl.h`：`ANLOGIC_IOCABORT = _IO('x', 11)`
- `cdev_sgdma.c` `char_sgdma_ioctl`：
  - 找到该 engine 的 `transfer_list` 首个 in-flight transfer
  - 置 `TRANSFER_STATE_ABORTED`，从 list 删除
  - `wake_up_interruptible(&xfer->wq)`
  - 释放 spinlock 后 `sgdma_engine_stop(engine)`
- `anlogic_pci_lib.c` `sgdma_xfer_submit`：
  - 增加 `case TRANSFER_STATE_ABORTED: rv = -ECANCELED`
  - 避免把 abort 当 timeout 再 abort 一次

源码保留在 `/home/kvdev/sgdma_drv_fix/`，**未安装**；原版驱动已恢复。

## 2. 实板测试

目的：让 H2C 写进入阻塞，再从另一个 fd 调 abort ioctl，测量释放时间。

方法：

1. recovery 后，单个进程打开 `h2c_0`。
2. 连续写 12 个 1952B TEST 帧，**不读 C2H**，让 H2C/C2H FIFO 逐步填满。
3. worker 线程在某个 `os.write` 阻塞；主线程检测到 1 s 无进展。
4. 主线程另开 `h2c_0` fd，调用 `ANLOGIC_IOCABORT`。
5. 记录 worker 返回、耗时和 dmesg。

实测：

```text
STALL after 6 writes
ABORT_IOCTL_OK
progress_count=6
worker_alive=False
aborted=True
abort_elapsed=0.001 s
worker_result=('OSError', '[Errno 125] Operation canceled')
```

dmesg：

```text
anlogic_pci:char_sgdma_ioctl: abort requested on 0-H2C0-ST xfer ... state 1
```

结论：

- abort ioctl 能在 **≈1 ms** 内唤醒并中止阻塞的 H2C `os.write`；
- worker 返回 `ECANCELED`；
- 代价是 SGDMA engine 停止，必须 fail-stop + recovery；
- 这不是“硬 deadline 保证”，只是可验证的 **bounded abort attempt**。

## 3. Host 侧封装

`status_adapter.py` 增加：

- `ANLOGIC_IOCABORT`
- `SgdmaAbort(node)`：打开节点并调用 abort ioctl
- `AbortableDevice(inner, abort_fn=...)`：
  - 把 `inner.write` 放在 worker 线程
  - 到 deadline 仍未返回时调用 `abort_fn`
  - 成功中止则抛 `DeadlineAbort`，不重试
  - `deadline_enforced` 仍委托 inner（保持 False）
  - `abort_supported=True` 仅表示“有 best-effort abort 路径”

离线测试：14 项全部通过（含 blocked write abort、正常写不 abort、abort_fn 失败、READY/FAULT/DONE/soft reset）。

## 4. 未解决

- **跨进程 C2H 复用**：process 1 成功后，process 2 仍可能在 RESET 后 C2H `Errno 512`。abort ioctl 不能修复；只有 PERST#/rebind 能恢复。
- 因此 B 的 RTL **SOFT_RESET/REINIT** 仍是硬需求；PC2 的 abort 路径只解决“在途阻塞写”这一半。
- `deadline_enforced` 不得因此改为 true；READY 预读 + abort 仍不等于硬 deadline。
- 真实 READY/FAULT/DONE 仍待 B 的新 RTL/bit。

## 5. 后续

1. B 确认 STATUS/CONTROL 的 BAR/偏移（候选 BAR0 0xA4/0xA8）并实现 RTL 软复位。
2. PC2 在新 bit 上集成 `StatusTransport` + `AbortableDevice`，跑负例：
   - 写前不 READY 快速拒绝
   - 在途阻塞写 deadline abort
   - 连续两个 H2C 进程无需 PCIe recovery
3. 通过后再做 v40 `RESET+30 TEST+8 ATTENTION`。

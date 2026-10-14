# H2C 阻塞写的超时问题：驱动核查与有界方案

状态：**已核查 + 已实现机制（本地验证）；实板验证已做（2026-04-27）——结果 NEGATIVE：deadline 未生效。**
日期：2026-10-11（板测更新 2026-04-27）。作者：PC2。

> 板测结论：阻塞的 H2C 写在我们的 0.5 s deadline **没有**被中断，返回于驱动 `h2c_timeout`=10 s。
> 即 SIGALRM 没有收紧上界（`_Deadline` 直到内核调用返回才触发）。因此 `deadline_enforced` 保持 **False**。
> 详见 [BOARD_VERIFICATION_CHECKLIST_H2C_DEADLINE.md](BOARD_VERIFICATION_CHECKLIST_H2C_DEADLINE.md)。

## 1. 问题

PC1 的 host plugin 因"传入 deadline 无法取消阻塞的 H2C `os.write`"而如实声明
`deadline_enforced=false`，导致实板探针不放行。需要**核查驱动行为**并给出**可验证的有界方案**，且不改驱动/系统。

## 2. 驱动核查（vendor `anlogic_pci` 源码 + sysfs）

写路径：`cdev_sgdma.c` `char_sgdma_write` → `char_sgdma_read_write`，其中：

```c
res = sgdma_xfer_submit(sgdev, engine->channel, write, *pos, &cb.sgt,
                        0, write ? h2c_timeout * 1000 : c2h_timeout * 1000, NULL);
```

`anlogic_pci_lib.c` 的 `sgdma_xfer_submit` 在提交描述符后等待：

```c
if (timeout_ms > 0)
    al_wait_event_interruptible_timeout(xfer->wq, (xfer->state != TRANSFER_STATE_SUBMITTED),
                                        msecs_to_jiffies(timeout_ms));
else
    al_wait_event_interruptible(xfer->wq, (xfer->state != TRANSFER_STATE_SUBMITTED));
```

- `al_wait_event_interruptible_timeout` = **有界且可被信号中断**的等待。
- `h2c_timeout` / `c2h_timeout` 是 module param，**默认 10 秒**；sysfs 实测：
  `/sys/module/anlogic_pci/parameters/h2c_timeout = 10`、`c2h_timeout = 10`。
- 超时/被中断时走 `default` 分支：读 engine status → `transfer_abort` → `sgdma_engine_stop`，返回 **`-ERESTARTSYS`**（到用户态为 `-EINTR`）。
- 写入前有 `check_transfer_align`（对齐校验）。
- **活证**：之前 H2C 写卡住时，`Ctrl-C`（SIGINT）能立即打断 —— 证明该等待确实**可中断**。

## 3. 结论

1. H2C `os.write` **不是无限阻塞**：其上界是驱动 `h2c_timeout`（默认 **10 s**）。
2. 该等待**可被信号中断**，因此可以用信号把上界**收紧到我们 per-request deadline**。
3. 代价：被中断/超时会让驱动 **停掉 SGDMA 引擎**，所以之后必须 **RESET** 才能复用 —— 这是"abort-and-recover"，不是"干净取消"。

## 4. 已实现的有界机制（`pcie_transport/sgdma_device.py`）

- `_interruptible_deadline(deadline)`：主线程下用 `signal.setitimer(ITIMER_REAL, deadline - now)`
  装一个会抛异常的 SIGALRM；`os.write` 期间触发即中断内核的 interruptible 等待。
- `SgdmaDevice.write` 用其包住 `os.write`；中断 → `TransportError`（提示"引擎已停，需 reset 复用"）。
- **不是**外层 Python timeout：信号真的中断了阻塞的系统调用。
- 平台/线程守卫：仅 POSIX 且主线程生效；否则该上下文 `yield False`，退回驱动 `h2c_timeout` 上界。
- `SgdmaDevice.deadline_enforced` 属性如实反映机制是否生效；`host_plugin.metadata()` 用它填 `deadline_enforced`。
- C2H 读本就用 `select` + deadline（有界），无需信号。

本地验证：`pcie_transport/tests/test_sgdma_deadline.py`（用匿名管道模拟阻塞 fd，验证在 deadline 处中断、deadline 过期即报错、非主线程不武装）。

## 5. 实板验证（2026-04-27 已执行）——结果 NEGATIVE

板测发现：正常回归通过；用未实现的 `ATTENTION` 帧确实能造出阻塞写；但该写**没有**在我们的 0.5 s deadline
被中断，而是返回于驱动 `h2c_timeout`=10 s（dmesg 见驱动自身 `xfer … timed out`）。超时后需完整恢复。
→ 机制**未生效**，`deadline_enforced` 必须保持 False。原计划步骤保留如下供追溯。

1. 制造一个**不会被消费的 H2C 帧**（例如 endpoint 不接收该请求 / 临时停消费），对 `h2c_0` 发一帧，
   传入小 deadline（如 0.5 s）；断言 `os.write` 在 **≈deadline** 返回并抛错，**而非 10 s**。
2. 之后确认必须 `RESET_CACHE` 才能恢复（引擎已停）。
3. 正常路径回归：30 轮 `OP_TEST` 时长分布不变（无副作用）。
4. 记录：命令、deadline、实际返回时间、`dmesg`、`h2c_timeout` 值、结论。

## 6. 声明口径

- 机制生效时：`deadline_enforced=true`（**写**被收紧到 deadline；超时=abort→reset）。
- 机制不生效（非 POSIX / 非主线程）时：`deadline_enforced=false`，仅有驱动 `h2c_timeout` 上界。
- 无论哪种，**绝不**用"外层加 Python timeout"冒充已解决。

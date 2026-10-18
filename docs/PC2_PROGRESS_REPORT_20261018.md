# PC2 进度报告：H2C 超时、恢复与状态接口（2026-10-18）

- 作者：PC2
- 日期：2026-10-18（PC 接收日期；板卡时钟异常显示 2026-04-27，不作为日期依据）
- 团队决定：**采用方案 B**；不以方案 A 的显式风险接受放行 v40 NPU→FPGA。
- 状态：**PC2 侧诊断、host 路径、接口草案、在途 abort 已验证；RTL 状态/软复位与新 bit 未完成。**
- 本文不代表方案 B 已实现或已通过实板验收。

## 1. 结论摘要

1. **H2C 阻塞写没有硬 deadline**：请求 0.5 s，实际 9.998 s 才返回；`deadline_enforced` 必须保持 **false**。
2. **跨进程复用仍不通**：process 1 的 RESET+30 TEST 通过后，process 2 可能在 RESET 后 C2H 读 `Errno 512`；仅 `rmmod/insmod` 不能恢复，只有 `pcie1-recover.sh`（PERST# + unbind/rebind）能恢复。
3. **驱动 close/stop 单独不够**：`reset_on_close=1` 的驱动补丁仍不能解决第二个进程；B 的 RTL **SOFT_RESET/REINIT** 是硬需求。
4. **Host BAR 路径已实测**：BAR0 走 `user` 节点/`bar_id=0`，BAR1 走 `control` 节点/`bar_id=1`；4B 对齐。
5. **接口草案**：STATUS 候选 **BAR0 + 0xA4**，CONTROL 候选 **BAR0 + 0xA8**；待 B 确认 RTL 空闲与语义。
6. **在途阻塞写可中止**：驱动增加 `ANLOGIC_IOCABORT`；实板 FIFO 填满后 worker 阻塞，abort ioctl 在 **0.001 s** 内释放写，worker 返回 `ECANCELED (125)`。这是 best-effort abort，不是硬 deadline。
7. **板卡已恢复原版驱动并 recovery**；自恢复后未发 H2C，等待新 bit/下一步。

## 2. 已证事实

### 2.1 阻塞 H2C 写

- 板卡：`linaro-alip`，kernel `6.1.99`，endpoint `1edb:abcd`
- 驱动：`anlogic_pci`，`poll_mode=1`，`h2c_timeout=10`，`c2h_timeout=10`
- 调用：`SgdmaDevice.write(32B, deadline=now+0.5)`
- 结果：`9.998 s` 返回，`TransportError: H2C write aborted at deadline`
- 结论：SIGALRM handler 在 `os.write` 返回后才执行；真正释放阻塞的是驱动 `h2c_timeout≈10 s`。`--timeout` 不是阻塞写的硬上界。

### 2.2 跨进程复用

```text
process 1（recovery 后）: RESET ok; REGRESSION OK=30 bad=0
process 2（新进程）:      C2H read failed [Errno 512]; Transport FAULT
仅 rmmod/insmod（不 PERST#）: process 2 仍失败
pcie1-recover.sh:          恢复；process 1 又 PASS
```

### 2.3 驱动单独修复不够

编译并安装 `reset_on_close=1` 的 `anlogic_pci.ko`（close 时 `sgdma_engine_stop`）：

- process 1 PASS；process 2 仍 `Errno 512`。
- 仅模块重载仍失败；只有 PERST#/rebind 能恢复。
- 结论：FPGA endpoint/DMA 侧需要 RTL 软复位；驱动 close/stop 不是充分条件。
- 修改版源码保留在板卡 `/home/kvdev/sgdma_drv_fix/`，**未安装**；原版已恢复。

### 2.4 Host BAR 可达路径（只读实测）

| 路径 | 实测 |
|---|---|
| `/dev/ANLOGIC-PCI0_control` + 4B pread | BAR1 (config) |
| `/dev/ANLOGIC-PCI0_user` + 4B pread | BAR0 (user) |
| `ANLOGIC_IOCR` bar_id=0/1 | BAR0/BAR1 |

当前 bit 只读值：

```text
BAR1 control 0x00 = 0x1fc08001
BAR0 user    0x5C = 0x56440013
BAR0 user    0x74 = 0x00000c01
BAR0 user    0x84 = 0x00002001
BAR0 user    0xA4 = 0x00000000
BAR0 user    0xA8 = 0x00000000
```

0xA4/0xA8 的 0 值**不是**新接口证据；需 B 在 RTL 确认空闲。

### 2.5 在途阻塞 H2C 写的中止

驱动补丁：

- `cdev_ctrl.h`：`ANLOGIC_IOCABORT = _IO('x', 11)`
- `char_sgdma_ioctl`：置 `TRANSFER_STATE_ABORTED`、从 transfer list 删除、`wake_up_interruptible`、`sgdma_engine_stop`
- `sgdma_xfer_submit`：`TRANSFER_STATE_ABORTED -> -ECANCELED`

实板测试：

```text
STALL after 6 writes
ABORT_IOCTL_OK
worker_alive=False
abort_elapsed=0.001 s
worker_result=('OSError', '[Errno 125] Operation canceled')
dmesg: abort requested on 0-H2C0-ST xfer ... state 1
```

边界：engine 会停止，必须 fail-stop + recovery；不是硬 deadline 保证。

## 3. 本次随报告提交的文件

- `docs/PC2_PROGRESS_REPORT_20261018.md`（本文）
- `docs/PC2_B_INTERFACE_FREEZE_DRAFT_20261018.md`（接口冻结草案）
- `docs/PC2_ABORT_IOCTL_EVIDENCE_20261018.md`（abort 证据）
- `docs/PC2_H2C_TIMEOUT_AND_RECOVERY_DECISION_20261016.md`（决策与实测）
- `docs/B_SOFT_RESET_AND_STATUS_DESIGN_20261016.md`（B 设计草案）
- `pcie_transport/status_adapter_20261018/`（host 状态/adapter + 14 项离线测试 + abort 测试脚本）

## 4. 未完成与边界

- B 的 RTL `READY/FAULT/DONE`、`SOFT_RESET` 与新 bit 尚未产生。
- 跨进程 C2H 复用仍需 RTL 软复位；abort ioctl 只解决在途写。
- 当前 `deadline_enforced=false`、`session_reusable=false`；不得改成 true 绕过。
- 实际 v40 NPU→FPGA 39 请求尚未在本阶段执行；CPU/HF v5 的既有结果不能替代。
- 性能数字含协议校验/证据落盘，不能当纯 FPGA 时间或外推 30 层。

## 5. 下一步（按方案 B 计划）

1. **接口冻结**：B 确认 STATUS/CONTROL 的 BAR/偏移（候选 BAR0 0xA4/0xA8）、位定义、读写副作用、复位/时钟域；PC1 审核 seq/layer/DONE 语义。
2. **RTL 实现**：B 加 `READY/FAULT/DONE` + `SOFT_RESET/REINIT`，仿真、TD 综合/P&R、新 bit。
3. **PC2 集成**：把 `StatusTransport` + `AbortableDevice` 接到真实寄存器；跑负例：
   - 写前不 READY 快速拒绝
   - 在途阻塞写 deadline abort
   - 连续两个独立 H2C 进程无需 PCIe recovery
4. **新 bit 回归**：RESET+30 TEST、CPU/HF v5 8 次 Attention、30 层隔离、非空 RESET。
5. **v40 单层**：上述放行后，在独占窗口跑 `RESET + 30 TEST + 8 ATTENTION`，交付 39 对原始帧和 hash。

## 6. 证据与版本

- 板卡证据目录：`/home/kvdev/work_pc2_pcie/h2c_deadline_evidence_20261016/`
- 修改版驱动源码：`/home/kvdev/sgdma_drv_fix/`（未安装）
- 原版驱动 SHA256：`fb04231eb5671a87f9b71f4b9e429fb7007bdcabcbddfebe11c640c10b21007e`
- 当前 bit：`attention_ddr.bit` SHA256 `C510C4FBA08D76B82FC5B1773BF460E60E920F12488627FF4BC64D09A9FAB378`（操作者声明）
- 团队计划：`docs/TEAM_WORK_PLAN_B_H2C_RECOVERY_20261018.md`（`codex/fpga-kv-attention` 分支）

本文只记录 PC2 当前进度与证据边界；开放问题仍以 `docs/UNKNOWNS.md` 为准。

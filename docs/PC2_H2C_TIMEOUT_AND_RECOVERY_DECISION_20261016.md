# PC2 H2C 超时与恢复门槛：结论与方案选择

- 文档日期：2026-10-16（PC 接收日期；板卡时钟异常显示 2026-04-27，不作为日期依据）
- 作者：PC2
- 状态：实测已确认；方案待团队选择
- 适用：RK3576 + PH1A90SEG324，contract v2，`attention_ddr.bit` / B 模式

## 0. 一句话结论

H2C 阻塞写**无法在 host/Python 层做成硬 deadline**：请求 0.5 s，实际 9.998 s 才返回；且 SGDMA engine **跨进程不可复用**，一次 `pcie1-recover.sh` 只能跑一个 H2C host 进程。`deadline_enforced` 必须保持 **false**。

短期用 **方案 A：显式接受 best-effort H2C + fail-stop** 解锁单层真实数据；长期用 **方案 B：RTL `READY/FAULT/DONE` 状态 + 驱动 engine reinit** 根治。

## 1. 实测事实

### 1.1 阻塞 H2C 写没有硬 deadline

- 板卡：`linaro-alip`，kernel `6.1.99`，endpoint `21:00.0 [1edb:abcd]`
- 驱动：`anlogic_pci`，`poll_mode=1`，`h2c_timeout=10`，`c2h_timeout=10`
- 代码：`pc2_consistent_20261016/pcie_transport/sgdma_device.py`，`deadline_enforced=False`
- 调用：`SgdmaDevice.write(32B, deadline=now+0.5)`
- 结果：

```text
requested deadline: 0.5 s
observed return:    9.998 s
exception:          TransportError: H2C write aborted at deadline
h2c_timeout:        10 s
```

SIGALRM handler 是在 `os.write` 返回后才执行；真正释放阻塞写的是驱动 `h2c_timeout≈10 s`，不是 0.5 s deadline。**`--timeout` 不是阻塞写的硬上界。**

对照：WSL POSIX 管道上的同一 `_interruptible_deadline` 能在 0.3 s 中断 `os.write`。所以这是 vendor 驱动阻塞等待的问题，不是 Python/SA_RESTART；`signal.siginterrupt` 不改变板卡结果。

### 1.2 SGDMA engine 跨进程不可复用

recovery 后：

```text
process 1（新进程）: RESET ok; REGRESSION OK=30 bad=0; p50=0.000347s; p95=0.000535s
process 2（另一个新进程）: FLUSH_OK; RESET 阻塞 10.240s;
                          C2H read failed: [Errno 512] Unknown error 512; Transport FAULT
```

`SgdmaDevice.flush_queues()` **不能**修复。第一个进程关闭 fd 后 engine 处于停止态，下一次 open 不会重新初始化。

结论：**真实 39 请求 session 必须是 recovery 后的第一个 H2C 进程。** 再跑任何 H2C 进程前都要重新 recovery。

### 1.2b 追加实验：驱动单独修复不够（2026-10-16）

为验证“只改驱动能否解决跨进程”，编译了 `reset_on_close=1` 的 `anlogic_pci.ko`
（`char_sgdma_close` 调 `sgdma_engine_stop`），安装并测试：

```text
recovery 后 process 1: RESET ok; REGRESSION OK=30 bad=0
process 2（新进程）:   仍 C2H read [Errno 512], Transport FAULT
仅 rmmod/insmod（不 PERST#/rebind）后再跑 process 2: 仍失败
只有 pcie1-recover.sh（PERST# + unbind/rebind）能恢复
```

结论：**FPGA endpoint / DMA 侧需要复位，驱动 close/stop 不是充分条件。**
B 不能只做驱动 engine reinit，必须同时有 RTL 软复位（或 host 可触发的 endpoint reset）
和 host 可读状态。当前已恢复原版驱动，板卡回到“下一个 H2C 进程可用”的状态；
修改版源码保留在 `/home/kvdev/sgdma_drv_fix/`，未安装。

### 1.3 阻塞写的板级副作用

阻塞写会让 H2C SGDMA engine 停止，内核连续打印：

```text
0-H2C0-ST not get comp desc at this poll work.
```

### 1.4 恢复流程已验证

`kvdev` 不在 sudoers；root SSH 和 `su`（kvdev 密码）都失败。恢复必须从板卡 root 串口/控制台执行：

```bash
/usr/local/sbin/pcie1-recover.sh
```

实际顺序：

```text
stop anlogic-sgdma -> rmmod anlogic_pci -> unbind rk-pcie ->
pcie1-fpga.sh（gpio-124 上电 + gpio-48 PERST# + bind）-> start anlogic-sgdma
```

恢复后 FACT：`lsmod` 有 `anlogic_pci`；`lspci` 有 `1edb:abcd`；`/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}` 存在；`pcie1-fpga`、`anlogic-sgdma` active；第一个 H2C 进程 RESET+30 TEST 全过。

## 2. 已有证据（`pc2_consistent_20261016`）

| 证据 | 内容 | 说明 |
|---|---|---|
| `results/refuse01` | 无 flag 时在发请求前拒绝 | 证明 gate 不是摆设 |
| `results/withflag01` | 真实 v5 输入，39 请求 / 8 Attention / 78 帧校验，bit-exact，`last_seq=3238` | 显式接受路径下功能通过 |
| `results/withflag01/manifest.json` | `deadline_enforced=false`，`session_reusable=false` | 声明与实测一致 |
| 本次 probe | 0.5s -> 9.998s；跨进程 Errno 512 | 本文新增证据 |

注意：`withflag01` 的输入是 PC1 **CPU/HF v5** 数据，不是 RK/NPU 实际导出；实际 NPU capture 仍为 `NOT_RUN`。它证明的是 transport + FPGA Attention 路径，不是 NPU→FPGA 实时链路。

## 3. 两个方案的区别

| 维度 | A. 显式接受 best-effort H2C | B. 驱动/RTL 修复 |
|---|---|---|
| 本质 | 承认 10s 阻塞写存在，项目层面接受风险 | 从根上消除阻塞写 / 跨进程失效 |
| 改动范围 | 只改 host gate/runner/manifest | 新 bit + host 轮询；可能改 vendor 驱动 |
| `deadline_enforced` | 仍为 **false** | 才可能为 true（需实测证据） |
| 单次阻塞上限 | 驱动 `h2c_timeout≈10 s` | 先查 READY 再写，正常不阻塞；异常快速失败 |
| 跨进程复用 | **一次 recovery 只能一个 H2C 进程** | 驱动 open/close 重置 engine，可反复跑 |
| 恢复 | 每个新进程前 root 跑 `pcie1-recover.sh` | 正常不再每次 rebind；故障仍有明确恢复 |
| 优点 | 快、低风险、不改基线，马上推进单层对拍 | 支撑 30 层、重复实验、性能/稳定性验收 |
| 缺点 | 10s 抖动、手动 root 恢复、实验效率低；不能做性能结论 | 周期长、需 B/FAE/vendor、新 bit 要重跑回归，技术风险高 |
| 适用阶段 | 现在：单层正确性/集成证据 | 后续：30 层、U/M、性能与最终验收 |

### A 的具体做法

- 保持 `deadline_enforced=false`、`h2c_timeout_s=10`。
- runner/session 增加显式参数，例如 `accept_unbounded_h2c=True`，并要求非空 operator note。
- manifest/events 记录：`deadline_enforced=false`、`h2c_timeout_s=10`、`accepted_by`、`fail_stop`、`auto_retry=false`、`auto_resend=false`。
- 超时/错误立即 FAULT，不重试、不追加 KV、不 CPU/mock 替代。
- 每次 recovery 后只跑一个 H2C 进程；真实 session 优先。
- **A 不是把能力做成 true，只是把已知风险写成可审计的接受。**

### B 的具体做法

1. **RTL 状态**：增加 host 可读的 `READY/FAULT/DONE`（BAR 或 control 寄存器）；host 先轮询再发 H2C，未 ready 快速失败，避免进入阻塞写。
2. **RTL 软复位**：增加 host 可写的 `SOFT_RESET/REINIT`（复位 H2C/C2H/DMA/endpoint 状态），不依赖 PCIe PERST#；这是跨进程复用的必要条件（驱动 close 单独已证明不够）。
3. **驱动**：在 open/close 或 ioctl 中配合软复位，并/或做 async submit + abort。
4. 新 bit 必须重跑现有 golden/隔离/RESET 回归；新 hash 单独登记。
5. 只有实测通过后，才讨论是否把 `deadline_enforced` 改为 true。

## 4. 推荐路径

**A 先解锁单层真实数据，B 并行推进 30 层/性能。**

- 现在：用 A 跑单层（当前是 CPU/HF v5；等 PC1 交实际 NPU capture 后再跑真实 NPU 单层）。
- 同时：PC2 出 `READY/FAULT/DONE` 寄存器映射和 host 轮询草案；B 评估 RTL 改动；PC2/FAE 评估驱动 engine reinit。
- 在 B 完成前，不把 A 的结果用于性能、30 层稳定性或最终验收结论。

## 5. 执行顺序（A 模式）

```text
1. root（PC1 串口）: /usr/local/sbin/pcie1-recover.sh
2. kvdev: 非 H2C preflight（只查 lspci/module/nodes）
3. kvdev: 真实 39 请求 session（必须是 recovery 后第一个 H2C 进程）
4. 结束；不要在同一 recovery 下再跑第二个 H2C 进程
5. 需要再跑：回到 1
```

可选 OP_TEST：必须放在同一个进程里，或在 OP_TEST 后再跑一次 recovery，不能单独占用“第一个进程”名额后再跑真实 session。

## 6. 边界与禁止说法

- 不得把 `deadline_enforced` 改成 true 来绕过 gate。
- 不得宣称“5s 硬超时已解决”；实测是 10s 驱动上界。
- 不得把 A 模式结果写成“性能通过”“30 层稳定”“生产 dtype 已冻结”。
- 不得自动重发会追加 KV 的请求；不得 CPU/mock fallback。
- `withflag01` 是 CPU/HF 输入；实际 NPU→FPGA 仍未证明。
- 板卡时钟异常，时间以 PC 接收时间为准。

## 7. 证据与文件

板卡：

```text
/home/kvdev/work_pc2_pcie/pc2_consistent_20261016/          # 代码/refuse01/withflag01
/home/kvdev/work_pc2_pcie/h2c_deadline_evidence_20261016/   # 本次证据
  README.md
  evidence.json
  board_h2c_probe.py
  board_h2c_probe.out
  recover.log
  preflight.sh
```

本地：

```text
C:\Users\meitianle\AppData\Local\Temp\opencode\pc2_evidence_20261016\
```

`preflight.sh` 默认**不发 H2C**，只查 endpoint/module/nodes；`--with-op-test` 会消耗第一个 H2C 进程名额，使用前要明确。

## 8. 待办

| 角色 | 动作 |
|---|---|
| PC1/B | 决定是否接受 A 模式；若接受，在 PC1 bridge / B session 中增加显式参数和证据字段 |
| PC1 | 提供实际 RK/NPU capture；确认串口/root 恢复窗口 |
| PC2 | 保持 false 声明；出 `READY/FAULT/DONE` 映射与 host 轮询草案；评估驱动 reinit |
| B | 评估状态寄存器 RTL 与 bit 回归；新 bit 单独登记 |
| 团队 | 在 B 完成前，不用 A 模式结果做性能/最终验收结论 |

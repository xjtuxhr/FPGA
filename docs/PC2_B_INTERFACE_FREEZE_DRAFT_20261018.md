# PC2+B 状态接口冻结草案（H2C 超时/恢复，2026-10-18）

- 状态：**草案，待 B 确认 RTL 偏移/语义，PC1 审核调用语义**
- 范围：PH1A90SEG324 endpoint、contract v2、B 模式
- 依据：`TEAM_WORK_PLAN_B_H2C_RECOVERY_20261018.md`；PC2 实测（2026-10-16/18）
- 约束：当前 bit **没有** host 可读应用状态；UART 不是 host 接口。本文不把旧摄像头 BAR 版本字当新接口。

## 1. 已实测的 host 可达路径

在真实板卡上以 `kvdev` 只读探测，未发 H2C：

| 路径 | 实测结果 |
|---|---|
| `/dev/ANLOGIC-PCI0_control` + `pread(fd,4,off)` | 读到 **BAR1 (config)** 的 4B 寄存器 |
| `/dev/ANLOGIC-PCI0_user` + `pread(fd,4,off)` | 读到 **BAR0 (user)** 的 4B 寄存器（驱动内部加 user base offset） |
| `ioctl(ANLOGIC_IOCR, bar_id=0, off)` | 读 **BAR0**；与 user 节点一致 |
| `ioctl(ANLOGIC_IOCR, bar_id=1, off)` | 读 **BAR1**；与 control 节点一致 |

实测值（只读，未改变状态）：

```text
BAR1 control pread 0x00 = 0x1fc08001
BAR1 control pread 0x04 = 0x00000000
BAR1 control pread 0x10 = 0xffffffff
BAR0 user    pread 0x5C = 0x56440013
BAR0 user    pread 0x74 = 0x00000c01
BAR0 user    pread 0x84 = 0x00002001
```

结论：

- host 可用的 32-bit 读写路径已确认：BAR0 走 `user` 节点/`bar_id=0`，BAR1 走 `control` 节点/`bar_id=1`。
- **偏移和寄存器值仍由 B 决定**；上面的 BAR0 0x5C/0x74/0x84 是旧例程/现有寄存器，**不是**新的 READY/FAULT/DONE。
- 只能 4B 对齐；不要假设 byte enable、读清零或写副作用。

## 2. 建议的状态寄存器

B 在 BAR0 或 BAR1 的空闲 4B 偏移实现（**具体偏移 TBD，由 B 在 RTL/约束中确认**）。

### 候选偏移（B 提议 0xA4，PC2 接受作为草案）

| 寄存器 | 候选位置 | 访问 | 状态 |
|---|---|---|---|
| STATUS | BAR0 + 0xA4 | 32-bit read | 草案，待 B 确认 RTL 空闲 |
| CONTROL | BAR0 + 0xA8 | 32-bit write | PC2 建议；若 0xA8 被占用，B 另选空闲 4B |

实测当前 bit（只读）：`BAR0 0xA4 = 0x00000000`、`0xA8 = 0x00000000`；
`0x90=0x00000001`、`0x94=0x00000000`、`0x98=0x00000064`、`0x9C/0xA0/0xAC/0xB0=0`。
**这些 0 值不是新接口证据**，B 必须在 RTL 中确认 0xA4/0xA8 未被其他逻辑占用。
host 访问：`/dev/ANLOGIC-PCI0_user` 4B pread/pwrite，逻辑偏移 0xA4/0xA8；
或 `ANLOGIC_IOCR/IOCW` `bar_id=0, bar_offaddr=0xA4/0xA8`。

### STATUS（只读，4B）

| bit | 名称 | 含义 |
|---|---|---|
| 0 | DONE | 当前请求的逻辑计算完成、C2H output 就绪 |
| 3:1 | ERR | 0=OK, 1=SEQ, 2=LAYER/POS, 3=CRC/FORMAT, 4=AXI/DDR, 5=INTERNAL, 6..7 reserved |
| 4 | READY | endpoint 可接收新 H2C（PCIe 链路、DDR ready、接收 FIFO/parser 空闲） |
| 5 | FAULT | endpoint 需要显式 SOFT_RESET；host 必须停止 |
| 6 | BUSY | 正在处理一层（可选） |
| 31:7 | reserved | 以后放 layer/position/perf counter |

建议语义：

- `READY=1` 只表示“现在可接收”；host 写 H2C 前必须重新读一次。
- `DONE` 针对当前请求身份；host 必须同时校验 C2H 的 seq/layer/position，旧 DONE 不能满足新请求。
- `FAULT` 锁存，直到 SOFT_RESET；host 不得在 FAULT 下继续发送。
- `ERR` 与 FAULT 的关系由 B 定义：建议任一 ERR≠0 时 FAULT=1（或至少本请求不可用）。
- 读 STATUS 不应清除 DONE/FAULT；清除只能通过 SOFT_RESET 或新请求开始（由 B 明确）。

### CONTROL（只写，4B）

| bit | 名称 | 含义 |
|---|---|---|
| 0 | SOFT_RESET | 自清零；复位 H2C/C2H FIFO、parser FSM、Attention/KV 写 FSM、DMA/错误状态；不重置 PCIe HIP/BAR/链路 |
| 1 | SESSION_ABORT | 中止当前层并置 FAULT，等待 SOFT_RESET |
| 31:2 | reserved | 必须写 0 |

要求：

- SOFT_RESET 置位后，host 轮询 `READY=1 && FAULT=0` 才允许下一帧。
- 复位期间 `READY=0`。
- 复位后 KV 内容视为无效；下一 session 仍先发 RESET_CACHE。
- 软复位必须先 quiesce AXI master，避免中途复位导致总线挂死；CDC/同步由 B 处理。
- 建议加 VERSION（只读）以便 host 识别新 bit；可选。

## 3. Host 侧序列（B 模式）

```text
session_start:
  status = read STATUS
  if FAULT or not READY:
      write CONTROL.SOFT_RESET=1
      poll STATUS until READY=1 and FAULT=0 (bounded deadline)
  send RESET_CACHE
  for each layer/position:
      poll STATUS.READY=1 (bounded)
      if not ready: fail fast; no H2C
      write H2C frame
      poll STATUS.DONE=1 (bounded) or completion
      if FAULT or ERR != 0: FAULT; stop
      read C2H frame; verify seq/op/layer/position/CRC
  session_end:
      write CONTROL.SOFT_RESET=1 (optional, to leave endpoint clean)
      poll READY
```

硬性边界：

- **READY 预读只覆盖写前状态**，不能替代“在途阻塞写的中止试验”。
- 超时/FAULT 仍然 fail-stop，不自动重发追加 KV 的请求。
- 不用 CPU/mock Attention 冒充 FPGA 输出。
- `deadline_enforced` 只有在“READY 轮询 + 软复位 + 在途中止”实测通过后才讨论改 true。

## 4. 跨进程复用（已实测的硬需求）

2026-10-16 实验：

```text
驱动 reset_on_close=1（close 时 sgdma_engine_stop）:
  process 1: RESET + 30 TEST PASS
  process 2: C2H read [Errno 512] FAULT
仅 rmmod/insmod（不 PERST#/rebind）:
  process 2 仍失败
pcie1-recover.sh（PERST# + unbind/rebind）:
  恢复；process 1 又 PASS
```

结论：**驱动 close/stop 和模块重载都不够；RTL 软复位是跨进程复用的必要条件。**
B 不能只做驱动 open/close 重初始化；host 侧也不能只用 READY 轮询掩盖在途阻塞。

## 5. 负例/验收矩阵（接口冻结后执行）

| 用例 | 期望 |
|---|---|
| 上电/未就绪读 STATUS | READY=0, FAULT=0（或定义值）；host 不写 H2C |
| 变 READY | host 可发 RESET/TEST |
| 正常请求完成 | DONE=1, ERR=0；C2H 身份匹配 |
| 运行中失去 DDR ready | FAULT/ERR 置位；host 停止，不读 C2H |
| 坏帧/CRC/seq/layer | ERR 对应码；host FAULT，不重试 |
| RESET 后新会话 | 旧 DONE/旧帧不能满足新 seq；新历史正确 |
| 写前不 READY | host 快速拒绝，不进入 10s 阻塞写 |
| 在途写阻塞 | 在约定有限时间内中止/隔离；记录 monotonic、driver 日志、KV 状态 |
| 连续两个 H2C 进程 | 中间不做 PCIe recovery，各自 RESET/TEST 通过 |

“有限时间”阈值、故障注入方式和恢复状态必须在执行前由 PC1/PC2/B 写入测试计划。

## 6. 责任与待确认

| 项 | 负责 | 待确认 |
|---|---|---|
| STATUS/CONTROL 偏移、BAR、读写副作用 | B | RTL 地址、CDC、自清零、读清零、复位边界 |
| host 读/轮询/FAULT、adapter、driver 生命周期 | PC2 | 真实节点/偏移绑定、连续进程、有限等待/中止 |
| seq/layer/position/DONE 语义 | PC1 | 调度唯一负责人、旧帧防护、错误优先级 |
| 新 bit/回归/回退 | B+PC2 | 新 bit SHA256、TD 日志、旧 bit 保留 |

## 7. 版本与证据

- 团队计划：`TEAM_WORK_PLAN_B_H2C_RECOVERY_20261018.md`
- PC2 实测证据：`h2c_deadline_evidence_20261016/`（timeout、跨进程、driver-only 失败、recovery）
- 决策文档：`PC2_H2C_TIMEOUT_AND_RECOVERY_DECISION_20261016.md`
- 设计草案：`B_SOFT_RESET_AND_STATUS_DESIGN_20261016.md`
- 本文是接口冻结草案，不代表已实现或已通过实板验收。

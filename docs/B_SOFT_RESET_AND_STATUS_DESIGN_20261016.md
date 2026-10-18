# B 方案设计：RTL 软复位 + READY/FAULT/DONE 状态

- 日期：2026-10-16
- 作者：PC2
- 状态：**设计草案，未实现**；驱动单独修复已实测不足
- 适用范围：PH1A90SEG324 endpoint（`imx415_pcie_top`），contract v2，B 模式

## 0. 为什么需要这个设计

2026-10-16 实板实验：

1. 驱动 `reset_on_close=1`（`char_sgdma_close` 调 `sgdma_engine_stop`）已编译并安装。
2. recovery 后第一个进程：RESET + 30 TEST 全过。
3. 第二个进程：仍 `C2H read [Errno 512]`，Transport FAULT。
4. 仅 `rmmod/insmod`（不 PERST#/rebind）后第二个进程仍失败。
5. 只有 `pcie1-recover.sh`（PERST# + unbind/rebind）能恢复。

结论：**FPGA endpoint / DMA 侧需要复位，驱动 close/stop 不是充分条件。**
B 必须同时做：

- RTL 软复位/REINIT（host 可触发，不依赖 PERST#）
- RTL 状态字（READY/FAULT/DONE/ERR）
- 驱动/host 配合的状态轮询与软复位序列

## 1. RTL 状态字（建议）

现有 `PCIE003_INTERFACE_SPEC.md` 已定义 32-bit status：

- `[0]` DONE
- `[3:1]` ERR（0=OK, 1=SEQ, 2=LAYER, 3=CRC）
- `[31:4]` reserved

建议扩展（放在同一 4B status 读寄存器，保持既有位不变）：

| bit | 名称 | 含义 |
|---|---|---|
| 0 | DONE | 本层逻辑完成，C2H output 就绪 |
| 3:1 | ERR | 错误码；0=OK |
| 4 | READY | endpoint 可接收新的 H2C 帧（FIFO/parser/engine 就绪） |
| 5 | FAULT | endpoint 需要显式复位（不可继续） |
| 6 | BUSY | 正在处理一层（可选） |
| 31:8 | reserved | 以后放 layer/position/perf |

host 读法不变：4B control pread。**不要在未实现前臆造这些位。**

## 2. RTL 软复位控制（新增）

建议新增一个 4B control 写寄存器（偏移由 B 在 BAR1 空闲区确认）：

| bit | 名称 | 含义 |
|---|---|---|
| 0 | SOFT_RESET | 自清零；复位 H2C/C2H FIFO、parser FSM、attention/KV 写 FSM、DMA 状态 |
| 1 | SESSION_ABORT | 中止当前层，置 FAULT，等待 SOFT_RESET |
| 31:2 | reserved | 必须写 0 |

要求：

- **不重置 PCIe HIP / BAR / 链路**；只复位应用逻辑和数据通路。
- SOFT_RESET 置位后，host 轮询 `READY=1` 且 `FAULT=0` 才发下一帧。
- 复位期间 `READY=0`，host 不得发 H2C。
- 复位后 KV 内容可以视为无效；下一 session 仍先发 RESET_CACHE。
- 寄存器写要有跨时钟同步；不得在 AXI 事务中途强行复位导致总线挂死；建议先 quiesce，再复位。

## 3. Host 侧序列（B 模式）

```text
session_start:
  read STATUS
  if FAULT or not READY:
      write CONTROL.SOFT_RESET=1
      poll STATUS until READY=1 and FAULT=0 (bounded deadline)
  send RESET_CACHE
  for each layer/position:
      poll STATUS.READY=1 (bounded)     # 不 ready 就不发 H2C
      write H2C frame
      poll STATUS.DONE=1 (bounded); check ERR
      if ERR != 0: FAULT, stop
      read C2H
  session_end:
      write CONTROL.SOFT_RESET=1
      poll READY (optional)
```

关键点：

- 先查 READY 再写，避免进入 10s 阻塞写。
- DONE/ERR 由 status 读，不再只靠“收到匹配 C2H 帧”推断完成。
- 超时/FAULT 仍然 fail-stop，不自动重发追加 KV 的请求。
- `deadline_enforced` 只有在“READY 轮询 + 软复位 + 无阻塞写路径”实测通过后才讨论改 true。

## 4. 驱动侧

最小改动：

- `device_ops` 增加 control 节点访问（4B pread/pwrite）或复用现有 `ANLOGIC_IOCR`。
- `write` 前检查 READY；`wait_ready` 语义改为轮询 DONE/ERR，而不是“deadline 未过”。
- close 时可保留 `sgdma_engine_stop`，但**不能替代 RTL 软复位**。
- 不在驱动里伪造 status；所有位来自 RTL。

## 5. 验证计划（新 bit）

1. 单进程 OP_TEST 30/30。
2. **两个连续进程**，中间不做 PERST#/rebind、不做 rmmod/insmod：
   - process 1: RESET+30 TEST
   - process 2: RESET+30 TEST
   - 期望都 PASS。
3. 两个连续进程，中间写 SOFT_RESET：
   - 期望 process 2 PASS。
4. 真实 39 请求 session（CPU/HF v5 先跑），再做实际 NPU capture。
5. 故障注入：DDR not ready、FAULT、CRC、层/位置错误，确认 READY/FAULT/ERR 行为。
6. 记录新 bit SHA256、寄存器偏移、host/driver 版本；重跑既有 golden/隔离/RESET 回归。

## 6. 风险与非目标

- 软复位不得影响 PCIe 链路/BAR；需要 B 与 FAE 确认 HIP 复位边界。
- 复位 AXI master 前必须 quiesce，否则可能挂死总线。
- 新 bit 是新基线，需要重新登记 hash，不能暗改旧 bit。
- 本设计不改变 wire contract v2，不改变 QKV/输出 dtype/layout。
- 不把“驱动 close 停止 engine”当作跨进程复用已解决；实测已否定。

## 7. 参考

- `pcie_contract/PCIE003_INTERFACE_SPEC.md`（status 字既有定义）
- `pcie_transport/H2C_WRITE_TIMEOUT.md`（10s 阻塞写与 fail-stop）
- 本次证据：`h2c_deadline_evidence_20261016/`（timeout、跨进程、driver-only 失败、recovery）
- 决策文档：`PC2_H2C_TIMEOUT_AND_RECOVERY_DECISION_20261016.md`

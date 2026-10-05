# PCIE-003 接口 spec（草案，PC2）

状态：**DRAFT / 未冻结**。与 `contract.json` v2 对齐；逻辑线格式已确定，**BAR/地址/FIFO 实测**待实板枚举后填入 `TRANSPORT_BINDING.md`。
来源：本草案综合 `contract.json`、`README.md`、以及 FPGA 侧（B）`PCIE003_FPGA_REPLY.md` 的逐条确认。
不证明任何 Gate 通过；不改 `contract.json` 之前，一切以现有 codec 为准。

## 1. 线格式（沿用契约 v2，不变）

- 帧 = **32B header + payload**；线上 magic `4B 56 4D 58`（KVMX），`version=2`。
- 校验 **CRC-32/ISO-HDLC（IEEE）**，覆盖 header（crc 字段置零）+ 逻辑 payload；`123456789 → CBF43926`。
- op：
  - `RESET_CACHE`：32B header，空 payload，`layer=255, position=0`，响应同 seq 的 32B ack。
  - `ATTENTION`：H2C = **1920B**，C2H = **1152B**。
  - `TEST`：H2C = 1920B 已知 pattern，C2H = 输入前 1152B。
- **payload dtype = FP16 little-endian**（测试与首版生产对齐；生产 dtype 待 NUM-001）。
- 元数据：`layer=0..29`、`position=0..2047`；`seq` 非零递增、响应原样回显；**单请求在途**；无隐式 reset。
- 张量布局：head-major，每 head 64 项连续；`Q[9,64] → K[3,64] → V[3,64]`；`kv_head = q_head // 3`。

## 2. 每层数据流（B 已确认，C1 笔误已澄清）

```text
H2C 1920B：Q576 + K192 + V192（仅当前 token）
  → FPGA 把 K/V 写入 DDR（KV cache）
  → attention 时 FPGA 从 DDR 自读整段历史
  → C2H 1152B：attention output 576（FP16）
```

- **PCIe 只传当前 token**；KV 历史不走上链（与契约/方案 C 一致）。
- `start`：无独立握手线，等价于"收到本层请求第一拍"，由 header 的 layer/position/seq 触发。
- `done`：**FPGA 逻辑算完**（output 已就绪、可被 C2H 读走），**不含** C2H 到 host 的同步/校验。

## 3. 传输层约定（来自 B）

- 数据通路 **AXI-ST 风格**（`valid`/`last`/`ready` 背压），**不用 AXI-MM**。
- FPGA 侧 **收 FIFO 512×16bit、发 FIFO 512×16bit**（首版，可调）。
- 背压只拉低 `ready`，不阻塞 host 侧 SGDMA 的 H2C / notification。
- host 侧复用官方 **SGDMA 字符设备**：H2C/C2H 传 tensor；控制优先 user 节点 32bit pread/pwrite；保留官方 DMA 完成中断。

## 4. 完成与错误语义

- 契约模型：`RESULT_READY` 表示 output 稳定；仍须 C2H 完整读回 + seq/length/CRC/tensor 校验后 `CONSUMED`；任一错误 → `FAULT`。
- B 提供 **status 字 = DONE + error 码**：`0=OK, 1=SEQ_ERR, 2=LAYER_ERR, 3=CRC_ERR`。
- **待决（spec 需拍板）**：
  - transport 层错误（header magic/version/length/CRC 不符、seq 回显不符）→ 直接 `FAULT`。
  - 语义错误（SEQ_ERR/LAYER_ERR）由 FPGA status 返回，transport 映射到 `FAULT` 并按 `README §6` 走显式 reset 恢复。
  - error 码是**并入契约 response header**，还是**独立 status 寄存器**（transport 用 control 读）？PC2 倾向后者（不改线帧、对契约破坏最小）。

## 5. 性能（B 估算，首版上界，非验收值）

| 项 | 值 |
|---|---|
| T=64 实测 | ~1.95×10^5 周期/层 |
| T=256 估算（按 T 线性外推） | ~7.8×10^5 周期/层 |
| 88.9 MHz | ~8.8 ms/层 |
| 30 层 | **~264 ms/token**（首版上界） |

- 主要固定开销：softmax 的 32 拍除法；可换快速倒数 / 并行 head 优化。
- 该数字必须代入 `PLAN_C_VS_RK_ONLY_DECISION.md` 的收支平衡公式，与 RK-only 基线对比（勿单看 attention）。

## 6. 计时与验收边界

1. 先测**原始** 1920B 下发 / 1152B 返回链路可用。
2. 再测**framed v2**（含 32B header）：`TEST` 30 轮串行、每轮不同 counter、逐字节比对、错误数 0；记 min/mean/max/p95、30 轮总时间。
3. 真实 `ATTENTION` RTT 已含 FPGA 计算，**不再另加** attention 时间；`TEST` RTT 不含计算，才可另加。
4. 分测 transfer / sync / compute，禁止重复计重叠时间。

## 7. 开放/待决（TODO）

| # | 项 | 归口 |
|---|---|---|
| O1 | **FIFO 512×16bit = 1024B < 一帧 1952B**：单帧超 FIFO，需 ≥ 一帧 或确认 AXI-ST/SGDMA 支持帧中途背压 | B / PC2 |
| O2 | error 码并入契约 vs 独立 status 寄存器 | B / PC2 |
| O3 | 32→FP16 转换/舍入模块（B 未实现），依赖 NUM-001 | B / PC1 |
| O4 | BAR / 地址公式 / 实际 FIFO 深度（枚举后填 binding） | PC2 |
| O5 | 生产 QKV/output dtype/scale/layout（NUM-001） | PC1 |
| O6 | AXI-ST 数据通路是否即 SGDMA user 设备、`TLAST/TKEEP`/背压实测 | PC2 |

## 8. 变更流程

接口改动必须**同时**更新 `contract.json` + codec + golden + tests + 本 spec，并与 B 评审；不留半套版本。不同协议版本立即拒绝。

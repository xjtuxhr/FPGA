# PCIE-003 接口 spec（PC2）

状态：**逻辑接口已与 B 对齐（冻结候选）**；`contract.json` 无改动（线格式不变）。**BAR/地址/FIFO 实测**待实板枚举后填入 `TRANSPORT_BINDING.md`。
来源：`contract.json` v2、`README.md`、FPGA 侧（B）`PCIE003_FPGA_REPLY.md` / `PCIE003_FPGA_REPLY2.md`。
不证明任何 Gate 通过。

## 变更记录

- 2026-10-05 v0.1：初稿（DRAFT）。
- 2026-10-05 v0.2：按 B 的 `REPLY2` 定稿逻辑层——FIFO 2048/1024、独立 status 字、32→FP16 归 B、softmax 优化在计划内；解决 O1–O3。

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

## 2. 每层数据流（B 已确认）

```text
H2C 1920B：Q576 + K192 + V192（仅当前 token）
  → FPGA 把 K/V 写入 DDR（KV cache）
  → attention 时 FPGA 从 DDR 自读整段历史
  → C2H 1152B：attention output 576（FP16）
```

- **PCIe 只传当前 token**；KV 历史不走上链。
- `start`：无独立握手线，等价于"收到本层请求第一拍"，由 header 的 layer/position/seq 触发。
- `done`：**FPGA 逻辑算完**（output 已就绪、可被 C2H 读走），**不含** C2H 到 host 的同步/校验。

## 3. 传输层约定（B 已确认）

- 数据通路 **AXI-ST 风格**（`valid`/`last`/`ready` 背压），**不用 AXI-MM**；**数据通路 = SGDMA user 设备**（H2C/C2H）。`TLAST/TKEEP` 与背压确切时序待枚举后与官方例程对齐（PC2 绑定）。
- FPGA 侧 FIFO（v0.2）：
  - **收 FIFO 2048×16bit = 4096B**（容 1 帧 1952B + 余量）；
  - **发 FIFO 1024×16bit = 2048B**（容 C2H 帧 1184B + 余量）。
- **首版不依赖帧中途背压**：整帧进 FIFO 再处理，回避"SGDMA 长时间 stall 是否安全"的未验证点。若 DDR 写吞吐跟不上 H2C 到达率，再单独测背压（归 DDR-002）。
- host 侧复用官方 **SGDMA 字符设备**：H2C/C2H 传 tensor；控制优先 user 节点 32bit pread/pwrite；保留官方 DMA 完成中断。

## 4. 完成与错误语义（status 字）

- **独立 status 字**（32-bit，4B control pread 读），不改线帧：
  - `[0]` = **DONE**（本层逻辑算完、output 就绪）
  - `[3:1]` = **ERR**（`0=OK, 1=SEQ_ERR, 2=LAYER_ERR, 3=CRC_ERR`）
  - `[31:4]` = reserved（后续放 perf counter / layer / position）
- **读序**：host **先读 status**（poll DONE / 等完成中断）；`ERR=0` 才读 C2H；`ERR≠0` 走显式 reset 恢复，**不读 C2H**。
- transport 层错误（header magic/version/length/CRC 不符、seq 回显不符）→ 直接 `FAULT`；语义错误（SEQ_ERR/LAYER_ERR）由 status 返回并映射到 `FAULT` + 显式 reset。

## 5. 性能（B 估算，首版上界，非验收值）

| 项 | 值 |
|---|---|
| T=64 实测 | ~1.95×10^5 周期/层 |
| T=256 估算（按 T 线性外推） | ~7.8×10^5 周期/层 |
| 88.9 MHz | ~8.8 ms/层 |
| 30 层 | **~264 ms/token**（首版上界） |

- 主要固定开销：softmax 的 32 拍除法；**B 计划内首要优化**（快速倒数 / 并行 head），会显著压低上界。
- 该数字须如实代入 `PLAN_C_VS_RK_ONLY_DECISION.md` 的收支平衡，与 RK-only 基线对比（勿单看 attention）。

## 6. 计时与验收边界

1. 先测**原始** 1920B 下发 / 1152B 返回链路可用。
2. 再测**framed v2**（含 32B header）：`TEST` 30 轮串行、每轮不同 counter、逐字节比对、错误数 0；记 min/mean/max/p95、30 轮总时间。
3. 真实 `ATTENTION` RTT 已含 FPGA 计算，**不再另加** attention 时间；`TEST` RTT 不含计算，才可另加。
4. 分测 transfer / sync / compute，禁止重复计重叠时间。

## 7. 开放/待决（TODO）

| # | 项 | 状态 | 归口 |
|---|---|---|---|
| O1 | FIFO 深度 ≥ 一帧 | ✅ 解决：收 2048×16bit、发 1024×16bit，不走帧中途背压 | B |
| O2 | error 码放哪 | ✅ 解决：独立 status 字（`[0]`DONE / `[3:1]`ERR） | B/PC2 |
| O3 | 32→FP16 转换模块 | ✅ 解决：**B 实现**（`q88_to_fp16` 占位先行），NUM-001 冻结后只改舍入/scale | B/PC1 |
| O4 | BAR / 地址公式 / 实际 FIFO 深度 | 待枚举后填 binding | PC2 |
| O5 | 生产 QKV/output dtype/scale/layout（NUM-001） | 待 PC1 冻结 | PC1 |
| O6 | AXI-ST `TLAST/TKEEP`/背压实测 | 待枚举后与官方例程对齐 | PC2 |

## 8. 变更流程

接口改动必须**同时**更新 `contract.json` + codec + golden + tests + 本 spec，并与 B 评审；不留半套版本。不同协议版本立即拒绝。

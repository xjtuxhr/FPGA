# FPGA DDR 访问需求（给 FPGA 老师，DDR-001/002 输入）

> 本文由 FPGA 侧（B）起草，作为配 DDR IP 和读写校验的输入。未冻结项都标了 CANDIDATE。

## 背景

方案 C：SmolLM-135M，FPGA（PH1A90SEG324）负责 KVmix/Attention，FPGA 侧 256 MiB DDR 存
完整 KV cache + metadata + buffers。首版 context T = 64/128/256，head_dim D = 64，KV 头 G = 3，Q 头 H = 9。

## KV cache 访问模式（配 DDR IP 的核心输入）

| 操作 | 频率 | 数据量 | 说明 |
|---|---|---|---|
| 写新 token | 每 decode 一步 | K+V = G×D×16bit×2 = **768 B** | FP16（recent tail） |
| attention 读 | 每 decode 一步 | T×768 B，T=256 时 **≈192 KB** | 读全部有效 token 的 K/V |
| tail 重新量化 | 每 decode 一步（T>M 后） | 读 768 B + 写 codes+scale+min（K2/V2 时 ≈96 B） | 最旧 recent token 从 FP16 转量化 |

**读吞吐主导**：每步读 ~192 KB vs 写 ~1.5 KB，相差两个数量级。请老师确认 DDR 读写并发与有效带宽能否支撑。

## 需要老师确认（DDR-001）

- 用户侧位宽（×16 / ×32 / ×64）、最大 burst 长度、实际时钟/速率；
- 读延迟、写延迟（CAS 等时序参数）；
- 能否**同时读 + 写**（DDR-002 的 KV 读与 tail 量化写会重叠）；
- 地址映射 / bank 结构、按 KV head / token 对齐是否有收益。

## 交付请求

1. DDR IP 的用户侧接口参数（位宽、burst、延迟）；
2. 一个最小读写校验例程：写已知 pattern → 读回比对，作为板上 DDR 闭环的起点（D7 里程碑）。

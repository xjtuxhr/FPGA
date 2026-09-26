# HISTORICAL：全 FPGA 计算架构分析

2026-09-26被方案 C 取代；当前入口为 [COMPUTE_ARCHITECTURE](COMPUTE_ARCHITECTURE.md)。下文的 FROZEN/主线等标签保留原历史语境，不表示当前决策。FPGA GEMV、LM Head、完整权重驻留/扫描不再属于主线；旧预算命令须添加 `--architecture full_fpga`。

状态：2026-09-26。正式模型重选，Smol135M为当前预算候选；15M/42M不再是算法效果交付模型。已有本地checkpoint/header核对与PC量化结果总结，无完整LM RTL综合/板上带宽证据。先读 [PLAN](../PLAN.md)，模型证据见 [MODEL_AND_PC_RESULTS](MODEL_AND_PC_RESULTS.md)，开放问题只在 [Registry](UNKNOWNS.md)。

本文用 **FROZEN** 表示项目决定或已核实的参考源码行为，用 **DERIVED** 表示注明前提的算术结果，用 **CANDIDATE** 表示待实验的设计方向。模型源码事实不等于当前板上实现事实。

## 1. Scope 与证据

- **FACT（用户规格截图）**：器件口径为PH1A90SEG324，240 DSP、272个20K ERAM/5440K总量；DDR1066 Mbps/x16、8路SerDes/10.3125 Gbps、148 IO、MIPI未列。见 [硬件事实](HARDWARE_FACTS.md)。DDR引脚侧条件上限2.132 GB/s不是有效带宽，lane/tile仍不得冻结。
- **FROZEN（项目）**：batch=1、逐 token 自回归；PH1A90 完成完整模型计算；首版 W8；一套计算单元逐层复用；DDR 保存权重和完整 KV；U=全层全 token K2/V2、无近期 FP16，M=重要层 K3/V4、其余 K2/V2、带近期 FP16。见 [PLAN](../PLAN.md)。
- **FACT（参考实现）**：[llama2.c 模型定义](https://github.com/karpathy/llama2.c/blob/master/model.py)与[逐 token C 实现](https://github.com/karpathy/llama2.c/blob/master/run.c)给出投影、RMSNorm、RoPE、SwiGLU、Attention 顺序。项目 [预算工具](../tools/budget_check.py)记录当前采用的 15M 维度。
- **FACT（本地候选）**：Smol config与safetensors header已核对，tie=true、参数134,515,008；15M/42M bin header共享标志也已读。正式上板模型/PC配置一致性仍需MODEL/EVAL确认，不把候选提升为冻结目标。

## 当前 Smol135M 预算（FACT / DERIVED / CANDIDATE）

形状FACT：L30、D576、FFN1536、QH9/KVH3、HD64、V49152、原生T2048。完整batch1流程：

```text
token ID → embedding[576]
→ 30 × [RMSNorm → Q[576]/K[192]/V[192] → RoPE(Q,K)
         → KV写入 → 9Q头共享3KV头的QK → softmax → PV → O → residual
         → RMSNorm → gate/up[1536] → SiLU×up → down[576] → residual]
→ final RMSNorm → LM Head[49152,576] → 完整logits[49152]
```

按每个block（不含非线性等）：Q/O各331,776 MAC，K/V各110,592 MAC，gate/up/down各884,736 MAC。固定线性共3,538,944 MAC/block，LM Head=28,311,552 MAC/token。全模型：

```text
线性MAC = 30×3,538,944 + 28,311,552 = 134,479,872
Attention MAC = 2×30×9×64×T = 34,560T
总MAC = 134,479,872 + 34,560T
W8一遍主矩阵+head+embedding一行 = 134,479,872 + 576 = 134,480,448 B
FP16 KV bytes = 2×30×3×64×T×2 = 23,040T
```

T64/128/256总MAC=136.692/138.904/143.327 M，W8读扫描约128.251 MiB/token。T256 Attention占约6.17%，head约19.75%，固定线性仍主导。GQA减少KV存储而不把Attention Q头MAC除3；需要重用K/V及解包结果才能达到预算一遍KV扫描，实际复用仍UNKNOWN。

KV默认容量、ERAM640 KiB、全W16超256 MiB、转换/量化开销见 [预算说明](BUDGET_GUIDE.md)。关键区别：B/U/M只换KV存储，模型MAC不变；反量化每压缩元素的affine multiply/add与bit extraction、U K部分组重算、M旧token迁移增加工作量。融合/直接低bit arithmetic可减少中间转换，但属于CANDIDATE；DSP/LUT节省不能按16/2推出。

当前共享GEMV、lane sweep、tile/banking原则继续适用，但不能把15M tile或48维RoPE直接搬来：Smol归约最长1536，9Q/3KV调度、64维旋转、30层误差累积、49152 head均需新golden。HF的RoPE旋转配对与llama2.c交错配对不同，ROM/权重导出需一致。上板T≤256不意味着更改模型原生context或RoPE theta。

**下方第2–10节保留为2026-09-23的15M历史推导/通用原则，不是当前正式模型冻结决定。** 其中checkpoint未知项已被本地header核对部分解决；新状态以上方、PLAN与Registry为准。

## 2. Model shape 与一次 token 的计算图

| 项目 | 当前参考配置 | 证据等级 |
|---|---:|---|
| block / hidden / FFN | 6 / 288 / 768 | FROZEN 目标配置；待实际 header 核对 |
| Q heads / KV heads / head_dim | 6 / 6 / 48 | FROZEN 目标配置；无 GQA/MQA 缩减 |
| vocab / max context | 32,000 / 256 | FROZEN 目标配置 |
| RMSNorm epsilon | `1e-5` | FACT：参考 C 实现；实际训练配置待核对 |
| RoPE | Q、K 相邻维成对旋转，theta=`10000` | FACT：参考源码 |
| activation | `W2(SiLU(W1(x)) * W3(x))` | FACT：参考源码，SwiGLU |
| embedding/head weight tying | 参考源码共享；本地15M header正vocab | FACT：2026-09-26本地header已核对 |

```text
token ID → embedding row[288]
→ 6 × [RMSNorm → Q/K/V → RoPE(Q,K) → KV 写入
       → QK dot → /√48 → softmax → PV → O → residual
       → RMSNorm → W1/W3 → SiLU×W3 → W2 → residual]
→ final RMSNorm → LM Head[32000×288] → logits[32000]
```

| 投影 | W `[rows, columns]` | 输入/输出 | decode 类型 |
|---|---:|---|---|
| Q/K/V/O，各一 | `[288,288]` | `[288]→[288]` | GEMV；每 row 是长度 288 的 dot |
| W1 gate、W3 up，各一 | `[768,288]` | `[288]→[768]` | GEMV |
| W2 down | `[288,768]` | `[768]→[288]` | GEMV |
| LM Head | `[32000,288]` | `[288]→[32000]` | GEMV |
| QK | 6 个 head × T 个 K[48] | 6T 个 score | 长度 48 的 dot |
| PV | 6 个 head × V[T,48] | 6 个输出[48] | 沿 T 归约 |

batch=1 decode 只有一个输入向量，所以投影按 GEMV 建模；不能把训练时的多 token GEMM 吞吐套到这里。逐 token prefill 可复用同一主要数据通路。

## 3. MAC budget（DERIVED）

定义 `T` 为含当前 token 的总可见长度，1 MAC = 1 次乘加；以下**不含**RMSNorm、RoPE、softmax、SiLU、解包、scale、PCIe 和 DDR 等待。

```text
单 block：Q/K/V/O 各 288²=82,944；W1/W3/W2 各 288×768=221,184
单 block 固定线性 MAC = 4×82,944 + 3×221,184 = 995,328
单 block QK = PV = 6×48×T = 288T
LM Head = 288×32,000 = 9,216,000
全模型 = 6×(995,328+576T)+9,216,000 = 15,187,968+3,456T MAC
```

| 全模型 MAC/token | T=32 | T=64 | T=128 | T=256 |
|---|---:|---:|---:|---:|
| QKV | 1,492,992 | 1,492,992 | 1,492,992 | 1,492,992 |
| QK + PV | 110,592 | 221,184 | 442,368 | 884,736 |
| O | 497,664 | 497,664 | 497,664 | 497,664 |
| MLP | 3,981,312 | 3,981,312 | 3,981,312 | 3,981,312 |
| LM Head | 9,216,000 | 9,216,000 | 9,216,000 | 9,216,000 |
| **合计** | **15,298,560** | **15,409,152** | **15,630,336** | **16,072,704** |

T=256 时 QK+PV 约占 5.5%，LM Head 约占 57.3%。少量 MAC 不意味着 Attention 控制、softmax 或 KVmix 解包简单。

**Prefill 口径**：交互式生成只需最后一个 prompt 位置的 logits，因此前 N−1 个位置可跳过 final RMSNorm/LM Head，但仍需全部 block 与 KV 写入。PPL/teacher forcing 为计算 `P(x[t+1] | x[0:t])`，每个被评分位置都必须产生 logits；不得用“生成 prefill 优化”跳过 PPL 所需的 head。

## 4. Memory traffic（DERIVED，附条件）

假设所有主矩阵为 W8，权重不跨 token 大规模驻留 ERAM，每个 decode token 至少流过六层线性矩阵与完整 LM Head：

```text
六层线性矩阵 6×995,328 = 5,971,968 B
LM Head       288×32,000 = 9,216,000 B
embedding 当前一行            =       288 B
合计                          = 15,188,256 B ≈ 14.49 MiB/token
```

这不是总 DDR 流量，还未计归一化参数、W8 scale、对齐、KV、重读和停顿。weight tying 影响存储副本数量，不消除 LM Head 每 token 的完整扫描。ERAM 名义约 680 KiB，仅为该次权重扫描量的约 4.6%，且要容纳其他 buffer；完整 W8 权重无法片上常驻。

以下是历史15M**容量快照**（KiB），用新 [budget_check.py](../tools/budget_check.py) 的 `--model stories15m --important-layers 2` 可复算，不是实测DDR读字节。metadata=4 B/组，K沿token、V沿channel，tail32；均是布局候选。新默认10%只取1层，不再默认复现本表；Smol新表见预算说明。

| T | B：FP16 | U：全 K2/V2，无尾部 | M：K2/3、V2/4 + 尾部 |
|---:|---:|---:|---:|
| 32 | 216 | 42.75 | 216 |
| 64 | 432 | 85.5 | 265.5 |
| 128 | 864 | 171 | 364.5 |
| 256 | 1,728 | 342 | 562.5 |

B 每个新 token 写入 `6×2×288×2=6,912 B`。U 全程压缩，M 的当前 token 先落近期 FP16 区，旧 token 迁出时再量化/重排；实际写放大和地址布局待定。预算工具还把 M 中尚未凑满的旧 K 分组临时按 FP16 计，因此快照里的 FP16 数据可超出显式尾部。上表的 M 尾部长 32 和重要层数 2 只是脚本预算假设，**不是**最终 KVmix 策略。

U 的 K 沿 token 轴分组时，尚未凑满的组仍必须是 K2；预算工具按部分组打包并计 4 B metadata。运行时如何随着新 token 到来更新这组的量化 scale 与 payload，见 [KV-008](UNKNOWNS.md)，不能把 FP16 临时尾部暗中加回 U。

ERAM 应保存当前 `[288]` 激活、两个 `[768]` FFN 临时向量、Q/score/accumulator、weight tile 与少量 KV buffer。层间临时激活通常不必落 DDR；跨 token 生存的完整 KV 必须按 PLAN 放在 DDR。完整 logits 的 PCIe payload：int8 31.25 KiB、int16/FP16 62.5 KiB、int32/FP32 125 KiB；logit dtype 尚未确定。

以 T=128 为例，可复算 `15,630,336 MAC + 至少 15,188,256 B W8 扫描 + B/U/M 一遍 KV 约 864/171/364.5 KiB + logits 传输`。完整系统延迟仍需板上测量。

## 5. Arithmetic intensity 与 GEMV 概念（CANDIDATE）

在 activation 保持 ERAM 时，W8 GEMV/MLP/LM Head 约 **1 MAC/权重字节**：一个权重通常只服务当前 token 的一次 MAC。B 的 FP16 QK/PV 粗略为 0.5 MAC/KV 字节；低比特 KV 增加按 payload 计算的强度，也增加 unpack/scale 工作。这些是下界直觉，不是 compute-bound/memory-bound 的实测判定。

主候选是一套参数化 W8 GEMV：`DDR burst → weight tile → P 个 MAC lane`，ERAM 中 activation 向 P lane 广播，accumulator 完成 row 后再缩放、舍入、饱和并写输出。Q/K/V/O、MLP、LM Head 可共享乘加核心；QK/PV 需要不同的 KV 地址顺序、概率输入与归约控制，可单独做数据通路或日后共享乘法资源。

**未冻结**：A8/A16、accumulator 位宽、每组/每 row scale、输出定点格式、P、DSP 映射与 tile 大小。满量程 W8×A16、归约长度 768 时有符号 32-bit 累加可能溢出；选位宽须依据范围证明和逐层 golden，不凭经验填 32。可作为待测 sweep 的点为 8/16/24/32 lane：覆盖低资源到较高并行，逐点记录 DSP、频率、ERAM、DDR stall 和端到端周期。此前“8–24 更稳妥”仅是 **CANDIDATE**，没有实测支持，不能当作设计结论。

## 6. 权重 tile 与物理读口（CANDIDATE）

示例 `W[768×288] × x[288]`：可按输出 row 分块，P=16 时每块 16×288 B，48 块；每个 row 保留一个 partial sum，`x[j]` 从 ERAM 广播。W2 改用长度 768。若 DDR 采用 row-major，便于**整行突发搬入**；它并不直接提供同一周期的 `W[row0,j]...W[rowP-1,j]`：在 DDR 中它们相隔整行。要实现 P lane 同时工作，必须有 `DDR burst → tile buffer → ERAM banking/transpose → P lane`，或改用适合 lane 的 DDR 交错布局。两种布局都尚未选定。

双缓冲只有在 DDR/ERAM 端口、仲裁和时序允许“读下一 tile 与算当前 tile 并行”时才有意义。QKV interleave 可能简化调度、复用片上输入向量，但不会减少三组矩阵的 W8 总字节。最终布局以连续突发测试和 bank 冲突测试决定。

## 7. Attention 与非线性数据通路

- **QK**：保存 q[48]，流式读取/解包每个历史 K，做长度 48 dot；六个 head 共保存 `6T` 个 score，T=256 时若用 32-bit 为 6 KiB。
- **Softmax**：score 按 head 求 max、减 max、exp 近似、求和、倒数近似、归一化。LUT/分段范围、饱和和中间位宽均为 UNKNOWN。
- **PV**：按历史位置流式读取/解包 V，广播该位置 softmax 概率，累加每头 48 个输出分量。
- **RMSNorm**：平方和归约、除以 288、加 epsilon、倒平方根近似、逐元素乘 norm weight；内部平方和/倒平方根精度待 golden 确认。
- **RoPE**：位置最多 0–255，theta=10000；可把所需 sin/cos 系数预计算入 ROM/LUT，不需要板上实时 `sin/cos` 浮点函数。ROM 格式/位宽未冻结。
- **SiLU/SwiGLU**：`x·sigmoid(x)` 需固定点查表或分段近似，再乘另一分支；LUT 区间/位宽以误差实测确定。
- **KVmix**：B 的 FP16 是 Cache **存储表示**，不强制 QK/PV 浮点算术。B/U/M 尽量在解包/转换后共享同一 Attention 定点通路；策略差异集中于 KV 存储、量化/反量化与迁移。不同存储模式的算术误差须逐层对拍。

K 按 token 轴分组时可按通道读取一组历史 K，并把 `q[channel]` 广播给若干 score accumulator；V 按通道轴分组时可按历史 token 读取 V，广播 `probability[t]`。这是适配预算布局的**候选**遍历顺序，不是已验证访存效率。

## 8. 六个互相独立的精度决策

“W8 模型”只冻结主矩阵的权重目标，不决定其余数值格式：

| 决策 | 当前状态 |
|---|---|
| weight precision | W8 是 FROZEN 目标；scale 布局 UNKNOWN |
| activation precision | A8/A16 等 UNKNOWN |
| accumulator precision | UNKNOWN；必须证明 288/768 长度无溢出 |
| KV storage precision | B FP16；U K2/V2；M 分层 K2/3、V2/4 + FP16 尾部为 FROZEN 策略边界 |
| nonlinear intermediate precision | RMSNorm/RoPE/softmax/SiLU 各自 UNKNOWN |
| logits precision | UNKNOWN；影响 32,000 元素的片上 buffer 和 PCIe 传输 |

## 9. Bring-up 与 golden verification

**CANDIDATE 顺序**：先用小整数向量验证 `GEMV + DDR 连续读取 → ERAM tile → 输出` 的闭环，再逐步接归一化、Attention 和一个 block。“Attention first”不适合作为本项目第一条核心硬件路径：固定线性层与 LM Head 占主要 MAC/W8 字节，且 GEMV+DDR 是它们共有的依赖。仍应尽早做 QK/softmax/PV 的独立数值实验，因为 MAC 小不代表容易。

未来至少建立以下逐级软件参考与 RTL 对拍向量：`gemv`、`rmsnorm`、`rope`、`qk`、`softmax`、`pv`、`silu`、`kv_quant`、`block`、`model`。每级记录输入格式、scale、舍入/饱和、容差、随机种子和原始输出；B/U/M 使用相同算术 golden 口径。尚无这些实现，不能勾选 PLAN 里程碑。

## 10. 上轮判断的证据分级

| 判断 | 当前类别 | 边界 |
|---|---|---|
| batch=1、逐 token、W8、B/U/M 定义 | FROZEN | PLAN 项目决定，不等于已有 RTL |
| 参考源码的 block 顺序、RMSNorm/RoPE/SwiGLU | FACT | 实际 checkpoint 尚待 pin |
| GEMV 形状、MAC 表、14.49 MiB 权重扫描下限 | DERIVED | MAC 由目标 shape；权重扫描另需 W8、无大规模片上缓存前提 |
| 共享 GEMV 核心、row tiling、8/16/24/32 sweep、双缓冲 | CANDIDATE | 需 DDR/DSP/ERAM/时序证据 |
| 本地15M/Smol tying | FACT，已更新 | header/config证据见模型事实；DDR/数值/KV metadata仍UNKNOWN |
| “DDR row-major 可直接每周期给 P lane 各一行同列权重” | ERROR，已修正 | 需要 tile buffer 重排/banking，或另选 DDR layout |
| “U 也有 FP16 recent tail” | ERROR，已修正 | PLAN 与脚本现统一为 U 无尾部 |

## 11. 状态索引

本文件的公式和架构候选不替代项目决策。未确认的 checkpoint、DDR、GEMV、数值、KV 和 host 接口统一进入 [docs/UNKNOWNS.md](UNKNOWNS.md)；阶段阻塞与实际进度看 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

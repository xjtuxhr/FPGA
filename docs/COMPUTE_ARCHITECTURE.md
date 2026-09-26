# CURRENT ARCHITECTURE：Smol135M异构KVmix/Attention

更新：2026-09-26。**FROZEN：方案 C；RK CPU/NPU=weight-heavy compute，PH1A90=KVmix/Attention accelerator。** 模型证据见 [MODEL_AND_PC_RESULTS](MODEL_AND_PC_RESULTS.md)，唯一开放问题源为 [UNKNOWNS](UNKNOWNS.md)。[旧全FPGA/GEMV分析](COMPUTE_ARCHITECTURE_FULL_FPGA_HISTORY.md)为HISTORICAL，不指导开发。

## 1. 标签与模型事实

FACT=直接证据/团队决定；DERIVED=明确公式；CANDIDATE=待测设计；UNKNOWN=无法确认。FROZEN表示团队边界，不等于MEASURED。
SmolLM-135M：30层、D576、FFN1536、Q/KV头9/3、HD64、vocab49152；GQA比例3，实际参数134,515,008。本地F32 checkpoint、272张量、538,090,408B；config BF16声明不改变文件实际dtype。embedding/head本地共享，正式制品签核见MODEL-001。

## 2. 单token图与归属

```text
RK：embedding → RMSNorm → NPU QKV → RoPE
 ↓ PCIe：Q[576],K[192],V[192]（已RoPE的Q/K，候选边界）
FPGA：写本层KV → 读因果历史KV → unpack/dequant → GQA QK → softmax → PV
 ↑ PCIe：attention output[576]
RK：NPU O → residual → RMSNorm → gate/up → SiLU×up → down → residual
 重复30层 → final RMSNorm → NPU LM Head → CPU sampling/detokenizer
```

QKV/O/MLP/LM Head为NPU冻结职责，但SDK接受shape、分图效率UNKNOWN。norm/RoPE/SiLU/embedding具体CPU/NPU归属是候选。不能用整模型RKLLM内部Attention，再让FPGA旁观冒充方案C。

RMSNorm需平方/均值/epsilon/倒平方根/缩放；RoPE需sin/cos与配对规则，Smol HF rotate_half不能直接套llama2.c相邻配对；SiLU/SwiGLU可由RK CPU/NPU承担，**不默认建设FPGA SiLU LUT**。精度/调用方式待对拍。首版T≤256不修改原模型2048配置。

## 3. MAC预算：DERIVED

每层linear：Q/O各331,776；K/V各110,592；gate/up/down各884,736，共3,538,944。
RK全层linear+LM Head：30×3,538,944 + 49,152×576 = **134,479,872 MAC/token**。LM Head=28,311,552，在RK侧，不能忽略。
FPGA QK+PV：**2×30×9×64×T=34,560T MAC/token**。

| T | RK linear M MAC | FPGA QK/PV M MAC | 两项合计 M MAC |
|---|---:|---:|---:|
| 64 | 134.479872 | 2.211840 | 136.691712 |
| 128 | 134.479872 | 4.423680 | 138.903552 |
| 256 | 134.479872 | 8.847360 | 143.327232 |

batch1 linear仍是GEMV式，但当前由NPU处理，不据此建立FPGA GEMV主线。MAC不计非线性/量化/搬运/等待，不能换算成已证实tok/s或DSP占用。脚本linear_macs/attention_macs与self-test可复现。

## 4. 存储与流量

RK LPDDR常驻完整权重：W8裸128.283508MiB、W16裸256.567017MiB；下载F32不是最终NPU制品。OS/workspace/layout副本另测；4GB不是权重独享。旧W8矩阵扫描128.25MiB/token属于RK内存侧，不是当前FPGA DDR/PCIe权重流量。

FPGA DDR完整KV+metadata+buffer。B=2×L×KVH×HD×T×2B；U/M候选group32、metadata4B、M重要层3、tail32、dense K3：

| T | B KV MiB | U KV MiB | M KV MiB |
|---|---:|---:|---:|
| 64 | 1.406250 | 0.263672 | 0.841553 |
| 128 | 2.812500 | 0.527344 | 1.118408 |
| 256 | 5.625000 | 1.054688 | 1.672119 |

metadata已含，勿重复添加。T256加1MiB候选buffer后DDR为6.625/2.054688/2.672119MiB；仅所列容量通过。U部分K组重算、M尾部+不完整旧K组留FP16是预算候选，不是正式迁移算法。GQA理想KV读一遍要复用，实际可能多遍，另有量化写入/迁移。

## 5. PCIe运行时载荷

每层下发960元素，返回576元素；16bit时1920B+1152B=3072B，30层**92,160B=90KiB/token**；8bit45KiB、32bit180KiB，均DERIVED。未计包头、DMA对齐、通知、重试、copy、cache sync；dtype未冻结。

层l返回后RK才算O/MLP、形成下一层QKV，batch1存在30次串行交互。若额外单次同步假设0.1/1/5ms，累计3/30/150ms，仅敏感性示例。不可用90KiB÷PCIe峰值宣布无瓶颈。

## 6. Attention-only ERAM与算术

CANDIDATE工作集140KiB：QKV4、KV tile64、score/prob24、PV accumulator8、unpack16、PCIe FIFO16、control8；额外预留64，总204KiB。非综合结果，IP/FIFO不得重复计；块宽深碎片、端口复制、alignment会改变结果。目标不用disRAM，不声称实现。脚本attention-workspace-kib/other-eram-reserve-kib可改。

B/U/M共享QK/PV/softmax路径，差异在存储/转换。B FP16是KV storage，不强迫Attention浮点。lane/accumulator/scale/softmax/dequant精度、banking、double buffer未冻结，不套旧GEMV lane结论。ERAM tile决定burst、共享K/V复用和调度，不只是“缓存”。

## 7. 验证与性能解释

golden至少覆盖RK linear/norm/RoPE/SiLU，FPGA qk/softmax/pv/kv_quant，以及attention/block/model。交互prefill可略前N−1 LM Head；PPL须每位置评分logits，均走真实Cache。B/U/M同NPU权重、转换与generation配置。

分测CPU、NPU、orchestration/conversion、PCIe transfer/sync、FPGA Attention/KV、端到端；避免重复计重叠时间。以同质量RK-only对照证明FPGA收益，短T/batch1可能被通信抵消。离线层重要性留PC。

近期核心证据是NPU shape + PCIe小包 + Attention-only，不再GEMV→完整Transformer RTL。

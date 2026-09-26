# 项目计划：面向FPGA的LLM推理KV Cache混合精度量化方法

更新：2026-09-26。**FROZEN：方案 C + HuggingFaceTB/SmolLM-135M 首次完整上板。** [旧计划](PLAN_FULL_FPGA_HISTORY.md)只供追溯；开放问题只维护在 [UNKNOWNS](docs/UNKNOWNS.md)。

## 1. 目标与职责

完成RK3576 CPU/NPU + PH1A90SEG324异构Smol135M推理系统，以FPGA的KVmix/Attention为研究核心，在相同条件下比较B/U/M；不是全部模型计算由FPGA完成。

| 部件 | 负责什么 |
|---|---|
| PC | Python离线重要性分析、模型/数值reference、TD开发、终端与结果分析 |
| RK3576 CPU | tokenizer/detokenizer、sampling、host控制、tensor调度/转换、NPU不适合的轻量算子 |
| RK3576 NPU | 主要linear engine：QKV、O、MLP、LM Head及其他适合NPU的weight-heavy计算 |
| RK LPDDR4X | 模型权重常驻；4GB名义容量也供OS/NPU工作区与副本使用 |
| PH1A90 | KV管理、KVmix quant/dequant、QK、softmax、PV、Attention状态、PCIe tensor接口、性能计数 |
| FPGA DDR | 完整KV Cache、metadata和buffers，不默认存完整模型权重 |
| FPGA ERAM | 当前层QKV、KV tile、scores/probabilities、PV accumulator、unpack/dequant、PCIe FIFO、control |

权重在哪里，weight-heavy计算尽量在哪里；**不以PCIe weight streaming为主线**。RoPE/RMSNorm可在RK CPU/NPU侧，具体主体/数值格式未冻结。embedding取行在RK侧，不把整张embedding送FPGA。

正式模型：30层、hidden576、FFN1536、Q/KV heads9/3、head_dim64、vocab49152、原生context2048；首版长度64/128/256。本地config/header/hash已核查，见 [模型证据](docs/MODEL_AND_PC_RESULTS.md)，正式制品与PC评测一致性仍需签核。stories15M等只作参考/必要单元调试，不是小模型全FPGA的前置验收。

## 2. 运行流程

```text
文本 → RK tokenizer → token IDs → RK embedding / norm / NPU QKV
 → RK RoPE（候选归属）→ PCIe Q/K/V
 → FPGA KV write → B/U/M Cache → KV read/dequant → QK → softmax → PV
 → PCIe attention output → RK O/residual/norm/MLP
 → 下一层（共30层）→ RK final norm/LM Head → logits
 → RK sampling → next token → 同一循环 → detokenizer → 用户文字
```

PC离线分析layer importance，策略加载到FPGA；不在FPGA计算梯度/重要性。PCIe每层传QKV/attention output，packet/layout未冻结。约90KiB/token只是16bit载荷推导；约204KiB ERAM只是候选。目标不用disRAM，须TD综合确认。

交互generation的prompt前N−1位置可跳过最终logits，但必须构造各层KV；PPL/teacher forcing须逐位置产生评分所需logits。prefill/decode共享主要异构路径。

## 3. 实验不变量

- B：FP16 KV存储，不等于整条Attention采用FP16浮点运算。
- U：全层、全token K2/V2，无recent FP16 tail，无KVmix特有机制。
- M：重要K层K3、重要V层V4，其他K2/V2，加recent FP16 tail；真实层ID离线产生。

固定同一Smol135M、权重、RK CPU/NPU linear路径、PCIe tensor格式、FPGA Attention算术、prompt/generation配置。仅KV存储、metadata、quant/dequant、policy、tail变化。group/scale/packing/tail为待验证参数，脚本默认不等于冻结。

分开记录CPU时间、NPU时间、orchestration/conversion、PCIe transfer/sync、FPGA Attention/KV、端到端token latency；记录资源/频率、KV bytes、DDR流量、PPL、next-token accuracy、生成样例。统一计时边界，不重复相加重叠区间。另设同质量RK-only对照，验证FPGA实际收益，不宣称天然更快。

## 4. 50天里程碑

D1沿用原始项目开工日，不因架构更新重置；实际日期/剩余天数需团队排期。已越过的门槛立即补证据，不伪造完成。

| 时间 | 工作与验收 |
|---|---|
| D1–D7 | TD/JTAG/UART + FPGA DDR闭环；核对SEG324/BOM/约束。确认RK SDK/runtime，PCIe官方例程链路与可访问buffer闭环，保留日志 |
| D8–D14 | NPU真实QKV/O/MLP/LM Head shape、M=1 latency、内存峰值、copy/sync；PCIe候选1920B下发+1152B返回往返与30层串行延迟；冻结数值边界 |
| D15–D21 | Attention-only B：QKV→KV DDR→QK→softmax→PV→output；分算子/单层golden，资源/timing，不用disRAM的目标验证 |
| D22–D28 | RK调度+30层B完整Smol生成；tokenizer/停止规则、逐位置PPL、端到端profiling |
| D29–D35 | U无tail与M策略/tail、metadata/迁移对拍；D29前冻结layout，按证据调整buffer/并行度，不暗换模型或变量 |
| D36–D42 | 固定prompt/dataset跑B/U/M和RK-only对照；质量/流量/吞吐/延迟/资源，优先tail-only及同字节随机策略消融 |
| D43–D50 | 锁定制品/脚本/配置，稳定演示、报告、复现；不新增Web/GUI或大模型路线 |

NPU shape不可用或30次同步抵消收益，应上报数据，由团队决定调整；Agent不能擅自恢复全FPGA或偷偷CPU-only替代冻结NPU职责。

## 5. 分工与工具

A：PC reference/模型/实验；B：TD/DDR/Attention RTL与综合（FPGA老师指导）；C：RK NPU benchmark/PCIe例程/调度验证；KVmix老师审核策略/数值/公平性。三人共同维护golden、制品版本与集成日志。

VSCode/Git管理源码；PC Python产生reference/策略；TD完成安路综合、P&R、bitstream，JTAG Programmer下载；UART/SSH终端只是调试入口；RK SDK/RKNN支持CPU/NPU；SGDMA例程不是现成Attention协议。

当前先验证NPU真实shape、PCIe小包、Attention-only。详细数据流见 [架构](docs/COMPUTE_ARCHITECTURE.md)，事实/进度见 [STATUS](docs/PROJECT_STATUS.md)。

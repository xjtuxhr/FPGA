# SUPERSEDED：全 FPGA 路线历史计划

仅供追溯。2026-09-26团队冻结方案 C + Smol135M，执行以 [当前 PLAN](PLAN.md) 为准。以下原文中的模型待选、完整 Transformer RTL、FPGA 权重/GEMV/LM Head、时间门槛均不再指导当前开发。旧预算命令应显式添加 `--architecture full_fpga`；当时的分析与失败结论仅适用于旧架构。

更新：2026-09-26。本文是协作者的唯一执行入口；历史论证、旧方案和网页抓取资料不作为日常任务清单。已纳入 `summary_of_PCtest.pdf`：15M/42M 不再是正式算法效果目标，模型进入重选；Smol135M 是当前已验证软件收益的预算候选，不是已经承诺上板成功。

## 1. 项目要完成什么

在 **安路 MLK-AFH03（PH1A90）** 开发板上运行一个完整的轻量自回归语言模型，比较三种 KV Cache 策略：

| 组别 | KV Cache | 用来说明什么 |
|---|---|---|
| B：基线 | FP16 KV Cache 存储 | 不使用 KV Cache 低比特量化时的 FPGA 基准 |
| U：统一量化 | 全部层、全部 token 均 K2 / V2；无近期 FP16 尾部 | 只使用统一低比特量化的收益与代价 |
| M：KVmix | 重要层 K3、V4；其余 K2、V2；近期 token 保留 FP16 | 层重要性引导的混合精度是否带来更好的质量/空间折中 |

项目的核心结论应来自同一板卡、同一模型、同一输入下的实测：**KV Cache 占用、生成吞吐/延迟、生成质量、FPGA 资源与频率**。不预设 KVmix 一定提高吞吐；在片上存储场景，它可能主要减少缓存容量。

## 2. 项目边界与待冻结的模型

| 项目 | 本期决定 |
|---|---|
| 板卡 | MLK-AFH03，器件规格按PH1A90SEG324；实物/TD/约束交叉核对，不混用SBG484 |
| 主模型 | 尚未冻结首次上板模型。优先预算 `HuggingFaceTB/SmolLM-135M`：30层、hidden576、FFN1536、Q/KV头9/3、head_dim64、词表49152、原生长度2048；继续筛选40–80M候选 |
| 演示任务 | 英文文本续写；不做中文聊天或通用问答；评测集与所选模型匹配 |
| 运行规模 | batch=1；先输入 32 token、生成 16 token；正式测试总长度 64/128/256，各生成 32 token |
| 模型计算 | FPGA 计算 embedding、Transformer 全部层和最终 logits；ARM/PC 不计算矩阵乘、注意力或 MLP |
| 权重 | 首版 W8；归一化和量化缩放参数按数值测试决定保留精度 |
| 层重要性 | 仅在电脑离线计算；FPGA 不做训练、反向传播、梯度或在线层排序 |
| 非目标 | 本期不做中文 UI、多 batch、自写 DDR 控制器、自写 PCIe、HLS 路线或 200 MHz 指标 |

`stories260K/15M/42M` 可供算子与接口联调，不作为证明 KVmix 优势的正式模型。PC 报告中 Smol135M 的 FP16/U/M PPL 为19.76/23.90/22.64（Wikitext-2）；这不能直接证明 W8 定点 FPGA 同样达到该质量。首次上板模型须由两位老师在质量复测、W8 数值、DDR 容量/带宽证据后确认，不能擅自截层或缩词表。Smol 与 PC 参数/证据详见 [模型与评测](docs/MODEL_AND_PC_RESULTS.md)。Qwen0.5B 保留远期预算，不进入50天性能承诺。

## 3. 三部分如何分工

```text
电脑（离线准备） ──策略/权重/测试向量──> ARM 或串口主机 ──控制/Token──> PH1A90 FPGA
                                                                    │
                                           logits/周期/状态 <────────┘
```

### 电脑：离线准备与实验分析

- 下载并固定模型、tokenizer、Python 和代码版本；
- 用 PyTorch 计算每层 K/V 投影的梯度范数，生成 `kv_policy.json`；
- 导出 W8 权重、定点测试向量和逐层 golden 输出；
- 在软件中完成 B/U/M、随机层分配对照、PPL 和 next-token 准确率评测；
- 保存原始日志、图表和版本哈希。

离线策略表只包含每层的 `k_bits`、`v_bits`、分组大小和近期 FP16 保留长度。它由 ARM/PC 写入寄存器或由 FPGA ROM 固化。**KVmix 的“选择哪层重要”不在 FPGA 上运行。**

### RK3576 ARM：控制与交互，不承担神经网络计算

目标职责：分词/反分词、加载策略和权重、配置 FPGA、启动一次生成、读取状态/性能计数器、从 logits 选择下一个 token、记录日志。

Type-C UART 仅用于点亮、寄存器和小测试向量调试，不能作为正式模型权重的常规装载通路（Smol W8裸权重约128.284 MiB）。最终路线必须使用板级验证的 FPGA DDR3L 控制器，并通过官方 RK3576-FPGA 工程或官方 DDR 装载方式写入权重；具体路径见 UNKNOWN Registry。D7前不通，团队立即决定是否调整目标；不能用串口慢速传完整权重或把小模型冒充正式成果。

ARM 选择 token 时，FPGA 已经产生完整 logits；它不执行模型层。报告必须分别列出 FPGA 核心时间和端到端时间。

### PH1A90 FPGA：保留项目必须的计算

- W8 权重读取与 GEMV；
- RMSNorm、RoPE、注意力 softmax、SwiGLU/MLP、残差；
- K/V 写入、FP16/低比特存储、分组量化和解包；
- QKᵀ 与 PV；
- 按层读取混合精度策略；
- 生成 logits、周期计数器和资源可综合的控制状态机。

Softmax、RoPE 和 SiLU 使用定点查表或分段近似，不实现浮点单元。先实现“解包/反量化后乘加”的正确版本；只有数值与资源证据表明必要时，才优化成按组融合计算。

B 的 FP16 指 KV Cache **存储格式**，不要求 QK/PV 使用浮点运算；B/U/M 尽量共用同一定点 Attention 算术路径，仅改变 KV 存储及对应解包/反量化，数值误差需逐层对拍。

### 存储分配

| 存储位置 | 本期用途 |
|---|---|
| PH1A90 ERAM | 当前层激活、权重 tile、KV读写缓冲、logits和控制状态；双缓冲需实测；不容纳完整正式模型权重/KV |
| FPGA DDR3L 256 MB | 必达：W8 权重、B/U/M 的完整 KV Cache、量化元数据；必须使用官方且板级验证的 DDR IP，不自写控制器 |
| ARM 侧存储 | tokenizer、权重文件、策略文件、日志；ARM 与 FPGA 的实际数据路径必须以原理图和官方例程为准 |

PH1A90 有240个DSP、约680 KiB ERAM。Smol W8裸权重约128.284 MiB，256 token的FP16 KV约5.625 MiB；完整权重/KV放DDR。完整32-bit logits需192 KiB，默认ERAM工作预算640 KiB且未计DDR IP等，余量紧张。Smol全W16裸权重约256.567 MiB，连权重都超过256 MiB预算；仅压缩KV不能解决此问题。容量充足不等于带宽/数值/时序可行，详见 [预算说明](docs/BUDGET_GUIDE.md)。

用户提供的SEG324规格为8路SerDes、10.3125 Gbps、DDR 1066 Mbps/x16、148用户IO、MIPI栏为“—”；详见 [硬件事实](docs/HARDWARE_FACTS.md)。x16在标称速率下的理论数据率为2.132 GB/s，不是实测带宽；256 MiB容量及PCIe Gen2 x1来自独立板级资料/预算，不能由截图推导。MIPI不作为已确认通路。

预算工具现直接输出上板判定：原始FP16权重在完整驻留路线下B/U/M均容量失败；W8的候选共享MAC核有DSP余量，但640 KiB工作区+64 KiB候选额外预留超680，当前缓冲方案不通过。减小候选tile可重新评估，不能把“有条件通过”当成已综合。1 tok/s、100 MHz、16 lane、每lane2 DSP、25% MAC利用率及额外预留只是敏感性场景，不冻结配置；详见预算说明第7节。

## 4. 最小可行架构

首版采用“一套计算单元逐层复用”的顺序结构，不追求大并行度。每生成一个 token：

1. 主机给出 token ID；
2. FPGA 读取 embedding，依次运行所选模型的全部 Transformer block（Smol为30层，不能减层冒充原模型）；
3. 各层将本 token 的 K/V 写入该层 Cache；读取历史 Cache 完成注意力；
4. FPGA 输出 logits 与周期数；
5. ARM/电脑选出下一个 token，并把它送回 FPGA。

这种架构的优先级是“完整、可验证、可重复”，不是追求论文 CUDA 的融合吞吐。prefill 可以逐 token 串行执行，与 decode 共用硬件；首 token 较慢应如实记录。交互式生成的 prefill 可跳过前 N−1 个位置的 final RMSNorm/LM Head；PPL 和逐位置 next-token 评测必须在每个被评分的位置生成 logits。

## 5. 开发顺序与 50 天里程碑

`D1` 是本计划发布后首次全员开工日。每个门槛必须留有代码、日志、波形、综合报告或测试 CSV；没有证据即未完成。

| 时间 | 算法/软件 | FPGA/板卡 | 集成与验收 |
|---|---|---|---|
| D1-D3 | 核对PC报告与候选模型；固定checkpoint/tokenizer及B/U/M；D3模型决策复审 | TD、点灯/JTAG/UART/ERAM，导入DDR工程 | 先建立权重/控制需求，不在缺证据时冻结runtime packet；向FAE索要工程 |
| D4-D7 | 离线梯度排名；软件 B/U/M Cache；导出 golden | 小整数 GEMV 仿真与上板；DDR 校准、读写、连续突发测试 | G1：软件可逐 token 生成；DDR 与 RAM/GEMV 正确 |
| D8-D14 | 定点数值模型；冻结位宽、饱和和近似误差 | GEMV、RMSNorm、RoPE、SiLU、softmax 单模块 | G2：必需算子可综合；确定 ARM/串口控制路线 |
| D15-D21 | 导出逐层对拍向量 | 单层 B：权重读写、注意力、FP16 Cache | G3：单层硬件结果与 golden 对齐 |
| D22-D28 | 质量回归 | 全部block逐层复用、完整logits、完整B | G4：FPGA连续生成至少32 token |
| D29-D35 | 冻结 KVmix 策略与随机对照 | U/M：量化、打包、按层位宽；仅 M 使用近期 FP16 尾部 | G5：B/U/M 均完整生成并记录数据 |
| D36-D42 | PPL/top-1、绘图、报告初稿 | 必要的访存/解包优化；资源、频率、功耗记录 | G6：可复现实验与演示录屏 |
| D43-D50 | 只修复交付问题 | 固定 bitstream 和测试配置 | 干净环境重跑、备份、答辩彩排、提交 |

止损规则：D7 前 DDR 校准、读写和权重装载通路不通，立即由两位老师决定是否调整模型/目标，不能隐性换成 260K；D14 前没有完整的单算子数值路径时，停止所有性能优化；D28 前基线 B 不能生成时，停止 ARM-PCIe 和 110M/Qwen 扩展；D35 前不能运行 M 时，需由两位老师确认是否调整目标，不能把 U 当成 KVmix 成果。

## 6. 三人分工和老师检查点

| 角色 | 主责 | 每周可见产出 |
|---|---|---|
| A：算法/软件 | 模型、离线重要性、量化参考、PPL/准确率 | `software/`、策略 JSON、测试 CSV |
| B：硬件 | RTL、安路工具、综合、下载、波形与时序 | `rtl/`、`sim/`、报告和板卡日志 |
| C：集成/测试 | 权重转换、串口/ARM 控制、回归、数据整理与演示 | `host/`、`results/`、运行说明 |
| KVmix 老师 | 审核重要性分析、分组轴、量化策略和对照公平性 | D3/D7/D21/D35 检查 |
| FPGA 老师 | 审核时钟、ERAM/DSP 映射、接口和时序 | D3/D7/D14/D28 检查 |

建议目录（均为待创建的开发产物）：

```text
software/  Python 参考模型、离线 profiling、定点数值模型
rtl/       SystemVerilog：gemv、nonlinear、kv_cache、model_top
sim/       单元/集成仿真、golden 对拍
host/      串口工具、后续 ARM 控制程序
configs/   固定 checkpoint 信息、kv_policy.json、数值格式
results/   原始 CSV、综合报告、图表、演示记录
```

## 7. 怎么判定“做成了”

### 正确性

- 固定 prompt 在软件与硬件模式下可复现；
- B/U/M 都真正读写自己的 KV Cache；
- FPGA 的逐层/逐 token 输出与同一数值格式的软件 golden 对拍；
- PPL 使用 teacher forcing 的逐 token Cache 路径，不使用一次性无 Cache forward 冒充结果；
- 量化策略与同预算随机选层至少比较 3 个随机种子。

### 数据表必须包含

| 指标 | B/U/M 都要有 |
|---|---|
| KV Cache 实际字节/ERAM 块数 | 是 |
| FPGA 时钟频率、LUT、DFF、ERAM、DSP | 是 |
| prefill、decode、端到端时间 | 是 |
| token/s 与输入/输出长度 | 是 |
| PPL、next-token top-1、样本数 | 是 |
| 固定文本续写样例 | 是 |

质量数据采用未参与策略调参的保留文本；Smol先复测Wikitext-2，不能与TinyStories不同tokenizer的PPL直接排名。旧“M相对B PPL增加≤5%”目标已被PC报告中的Smol约14.6%推翻，撤销为既定验收阈值。D7前在同checkpoint/上下文/分组/尾部/W8算术下复测后，由老师设新阈值；必须完整报告退化，不能测试集调参。U/M还需tail-only及同字节预算随机层对照，避免把全部收益归于选层。

## 8. 板卡与 FAE：第一周必须确认

请安路技术支持提供与 **MLK-AFH03、PH1A90SEG324、实际工具版本**一致的：

1. **已在 MLK-AFH03 上验证的 DDR3L 工程**：IP 版本、校准完成信号、用户接口、时钟/复位、约束、连续读写示例和实测带宽；
2. 权重从 RK3576/SD/Flash 写入 FPGA DDR 的官方参考路径；匹配SEG324的RK3576-FPGA PCIe工程及控制/数据路径说明。旧资料的MIPI线索需另核实物理引脚/IP，不能当作已可用退路；
3. JTAG、时钟、复位、UART、ERAM 的最小可运行工程和约束文件；
4. 目标器件的综合/布局布线/下载工具版本、许可证与仿真库；
5. `int8 × int8 -> int32` 乘累加映射到 DSP 的推荐 RTL/原语示例；
6. ERAM ROM 初始化、双口 RAM 和大容量拼接示例。

在得到第1项可运行证据前，正式模型不能进入RTL全模型阶段。指南给出FPGA-RK3576 PCIe Gen2 x1；可用驱动/DDR装载仍需板级闭环，不把物理规格当成已验证软件通路。

## 9. 常用文件与命令

| 需要做什么 | 位置 |
|---|---|
| 当前计划 | 本文件 `PLAN.md` |
| 当前状态与待填信息 | `docs/PROJECT_STATUS.md`（需在 D1 更新） |
| 为什么旧计划被废弃 | `docs/REVIEW.md` |
| PH1A 手册索引 | `references/README.md` |
| 内存预算估算 | `tools/budget_check.py` |
| 历史材料 | `archive/2026-09-21/`，不作为日常开发输入 |

```powershell
python tools/budget_check.py --architecture full_fpga --self-test
python tools/budget_check.py --architecture full_fpga
python tools/budget_check.py --architecture full_fpga --model smol135m --contexts 64 128 256
```

该工具含容量、MAC、转换/量化候选工作量与可选速率下界，不是综合结果或板上性能。量化只改变KV表示，不自动降低全模型MAC或DSP。默认重要层比例从旧20%改为PC报告的10%（向下取整、非零至少1层）；tail32、group32、dense K3、4 B metadata仍是预算假设，不是PC复现设置或冻结RTL。命令及兼容说明见 [预算说明](docs/BUDGET_GUIDE.md)。A/C在D3固定正式模型/数值/软件版本。

## 10. 参考边界

- `KVmix-arxiv.pdf`：算法背景和论文设定；不把 CUDA 代码直接当作 FPGA 实现。
- `references/hardware/DS900_PH1A_Datasheet.pdf`：器件资源与时序规格。
- `references/hardware/UG902_PH1A_ERAM.pdf`：ERAM 端口、初始化和模式。
- `references/hardware/UG904_PH1A_DSP.pdf`：DSP 乘法、累加和原语。
- `references/hardware/UG910_PH1A_HDL_Libraries.pdf`：需要显式实例化原语时查阅。
- `references/hardware/UG915_PH1A_DDR_old.pdf`：历史资料；不能替代当前 DDR IP 和板级例程。

本项目的创新点是：在完整 FPGA 轻量 LLM 推理链中，将离线层重要性分析得到的策略用于在线 K/V 混合精度 Cache 管理，并用统一量化与 FP16 基线证明其空间、质量和性能权衡。

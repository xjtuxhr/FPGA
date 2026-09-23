# 项目计划：面向 FPGA 的 LLM 推理 KV Cache 混合精度量化方法

更新：2026-09-23。本文是协作者的唯一执行入口；历史论证、旧方案和网页抓取资料不作为日常任务清单。

## 1. 项目要完成什么

在 **安路 MLK-AFH03（PH1A90）** 开发板上运行一个完整的轻量自回归语言模型，比较三种 KV Cache 策略：

| 组别 | KV Cache | 用来说明什么 |
|---|---|---|
| B：基线 | FP16 KV Cache 存储 | 不使用 KV Cache 低比特量化时的 FPGA 基准 |
| U：统一量化 | 全部层、全部 token 均 K2 / V2；无近期 FP16 尾部 | 只使用统一低比特量化的收益与代价 |
| M：KVmix | 重要层 K3、V4；其余 K2、V2；近期 token 保留 FP16 | 层重要性引导的混合精度是否带来更好的质量/空间折中 |

项目的核心结论应来自同一板卡、同一模型、同一输入下的实测：**KV Cache 占用、生成吞吐/延迟、生成质量、FPGA 资源与频率**。不预设 KVmix 一定提高吞吐；在片上存储场景，它可能主要减少缓存容量。

## 2. 已冻结的边界

| 项目 | 本期决定 |
|---|---|
| 板卡 | MLK-AFH03，FPGA 为 PH1A90 |
| 主模型 | `karpathy/tinyllamas/stories15M`：6 层、hidden=288、6 个 Q/KV 头、FFN=768、词表 32,000、原生总长度 256 |
| 演示任务 | 英文 TinyStories 风格文本续写；不做中文聊天或通用问答 |
| 运行规模 | batch=1；先输入 32 token、生成 16 token；正式测试总长度 64/128/256，各生成 32 token |
| 模型计算 | FPGA 计算 embedding、Transformer 全部层和最终 logits；ARM/PC 不计算矩阵乘、注意力或 MLP |
| 权重 | 首版 W8；归一化和量化缩放参数按数值测试决定保留精度 |
| 层重要性 | 仅在电脑离线计算；FPGA 不做训练、反向传播、梯度或在线层排序 |
| 非目标 | 本期不做中文 UI、多 batch、自写 DDR 控制器、自写 PCIe、HLS 路线或 200 MHz 指标 |

`stories15M` 是本期正式交付模型。`stories260K` 只可用于 GEMV、KV Cache 和串口接口的早期单元联调，不能代替 15M 作为正式实验结果。完成 15M 的 B/U/M 闭环后，才评估 `stories110M`；Qwen2.5-0.5B 需要重新评估权重容量、词表、带宽和工期，属于远期方向。

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

Type-C UART 仅用于点亮、寄存器和小测试向量调试，不能作为 15 MB 权重的常规装载通路。15M 的最终路线必须使用板级验证的 FPGA DDR3L 控制器，并通过官方的 RK3576-FPGA 传输工程或官方 DDR 装载方式写入权重。若该通路在 D7 前无法跑通，团队必须立即决定是否调整目标；不能用串口慢速传完整权重，也不能把 260K 冒充正式模型。

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
| PH1A90 ERAM | 当前层激活、权重 tile 缓冲、KV 读写缓冲、logits 缓冲和控制状态；是否双缓冲由 DDR/ERAM 实测决定；不尝试容纳完整 15M 权重或完整 KV Cache |
| FPGA DDR3L 256 MB | 必达：W8 权重、B/U/M 的完整 KV Cache、量化元数据；必须使用官方且板级验证的 DDR IP，不自写控制器 |
| ARM 侧存储 | tokenizer、权重文件、策略文件、日志；ARM 与 FPGA 的实际数据路径必须以原理图和官方例程为准 |

PH1A90 有 240 个 DSP、5,440 Kbit ERAM（约 680 KiB）。`stories15M` 的 W8 权重约 14.5 MiB，256 token 的 FP16 KV Cache 约 1.69 MiB，均必须在 DDR 中保存；ERAM 只保存一个计算 tile 的工作集。容量充足不等于带宽充足，必须测量 DDR 实际读写、缓存命中和计算空转周期。

## 4. 最小可行架构

首版采用“一套计算单元逐层复用”的顺序结构，不追求大并行度。每生成一个 token：

1. 主机给出 token ID；
2. FPGA 读取 embedding，依次运行 6 个 Transformer block；
3. 各层将本 token 的 K/V 写入该层 Cache；读取历史 Cache 完成注意力；
4. FPGA 输出 logits 与周期数；
5. ARM/电脑选出下一个 token，并把它送回 FPGA。

这种架构的优先级是“完整、可验证、可重复”，不是追求论文 CUDA 的融合吞吐。prefill 可以逐 token 串行执行，与 decode 共用硬件；首 token 较慢应如实记录。交互式生成的 prefill 可跳过前 N−1 个位置的 final RMSNorm/LM Head；PPL 和逐位置 next-token 评测必须在每个被评分的位置生成 logits。

## 5. 开发顺序与 50 天里程碑

`D1` 是本计划发布后首次全员开工日。每个门槛必须留有代码、日志、波形、综合报告或测试 CSV；没有证据即未完成。

| 时间 | 算法/软件 | FPGA/板卡 | 集成与验收 |
|---|---|---|---|
| D1-D3 | 跑 `stories15M` 原模型，固定 checkpoint/tokenizer；定义 B/U/M | 安装安路工具；点灯、JTAG、UART、ERAM 读写；导入 DDR/IP 例程 | 建仓库、确定权重布局与控制协议；向 FAE 索要当前板级工程 |
| D4-D7 | 离线梯度排名；软件 B/U/M Cache；导出 golden | 小整数 GEMV 仿真与上板；DDR 校准、读写、连续突发测试 | G1：软件可逐 token 生成；DDR 与 RAM/GEMV 正确 |
| D8-D14 | 定点数值模型；冻结位宽、饱和和近似误差 | GEMV、RMSNorm、RoPE、SiLU、softmax 单模块 | G2：必需算子可综合；确定 ARM/串口控制路线 |
| D15-D21 | 导出逐层对拍向量 | 单层 B：权重读写、注意力、FP16 Cache | G3：单层硬件结果与 golden 对齐 |
| D22-D28 | 质量回归 | 6 个 block 复用、logits 输出、完整 B 模式 | G4：FPGA 连续生成至少 32 token |
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

质量数据采用未参与策略调参的 TinyStories 保留文本。目标是 M 相对 B 的 PPL 增幅不超过 5%、top-1 下降不超过 2 个百分点；这是工程目标，不是论文或赛事承诺。若达不到，需报告结果并解释，不得在测试集反复调参。

## 8. 板卡与 FAE：第一周必须确认

请安路技术支持提供与 **MLK-AFH03、PH1A90、实际工具版本**一致的：

1. **已在 MLK-AFH03 上验证的 DDR3L 工程**：IP 版本、校准完成信号、用户接口、时钟/复位、约束、连续读写示例和实测带宽；
2. 权重从 RK3576/SD/Flash 写入 FPGA DDR 的官方参考路径；RK3576-FPGA PCIe/MIPI 工程及控制/数据路径说明；
3. JTAG、时钟、复位、UART、ERAM 的最小可运行工程和约束文件；
4. 目标器件的综合/布局布线/下载工具版本、许可证与仿真库；
5. `int8 × int8 -> int32` 乘累加映射到 DSP 的推荐 RTL/原语示例；
6. ERAM ROM 初始化、双口 RAM 和大容量拼接示例。

在得到第 1 项可运行证据前，15M 不能进入 RTL 全模型阶段。该板 FPGA-RK3576 的 PCIe 为 Gen2 x1；本期不以 PCIe 带宽作为吞吐承诺。

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
python tools/budget_check.py --self-test
python tools/budget_check.py --model stories15m --contexts 64 128 256
```

该工具是容量规划估算，不是综合结果或板上性能。主模型、模型代码和 tokenizer 的固定版本由 A/C 在 D3 写入 `configs/` 后再开始正式实验。

## 10. 参考边界

- `KVmix-arxiv.pdf`：算法背景和论文设定；不把 CUDA 代码直接当作 FPGA 实现。
- `references/hardware/DS900_PH1A_Datasheet.pdf`：器件资源与时序规格。
- `references/hardware/UG902_PH1A_ERAM.pdf`：ERAM 端口、初始化和模式。
- `references/hardware/UG904_PH1A_DSP.pdf`：DSP 乘法、累加和原语。
- `references/hardware/UG910_PH1A_HDL_Libraries.pdf`：需要显式实例化原语时查阅。
- `references/hardware/UG915_PH1A_DDR_old.pdf`：历史资料；不能替代当前 DDR IP 和板级例程。

本项目的创新点是：在完整 FPGA 轻量 LLM 推理链中，将离线层重要性分析得到的策略用于在线 K/V 混合精度 Cache 管理，并用统一量化与 FP16 基线证明其空间、质量和性能权衡。

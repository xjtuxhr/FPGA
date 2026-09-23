# 2026-09-21 审查记录

**历史记录，已被当前 [PLAN](../PLAN.md) 更新：**本页当时推荐 stories260K；此后团队已明确改用 stories15M 作为正式模型，260K 仅供早期单元联调。以下涉及“当前方案=260K、片上容纳完整模型”的段落是旧决策理由，不再指导实现。现行计算与存储口径见 [COMPUTE_ARCHITECTURE](COMPUTE_ARCHITECTURE.md)，开放问题见 [UNKNOWN Registry](UNKNOWNS.md)。

## 2026-09-23 计算架构自审修正

| 上轮报告的表述 | 修正 |
|---|---|
| 将源码中的 embedding/head tying 推成已核实的实际 15M checkpoint 性质 | 源码共享是 FACT；实际 checkpoint header/hash 未固定，保留 MODEL-002 UNKNOWN。预算参数数值明确标为共享假设。 |
| 把 row-major DDR 行布局与 P lane 同周期跨行取数连成一步 | DDR 可连续 burst 整行，但跨 P 行同列取数需要 tile buffer 的 banking/重排，或另选 DDR 布局。 |
| “8–24 lane 更稳妥”容易被读成配置决定 | 只是待测候选；按 8/16/24/32 sweep 观察资源、带宽、时序。 |
| prefill 跳过 LM Head 未限定用途 | 仅交互式生成前 N−1 个 prompt 位置可跳过；PPL/teacher forcing 每个被评分位置必须输出 logits。 |
| U 的预算错误保留 FP16 recent tail | PLAN 定义无 tail，已修复工具及 self-test；同时修正 V 的末尾部分通道组按满组计费。 |

本记录供老师和需要追溯的人阅读。当时的日常执行入口是 PLAN.md；当前另有计算架构与 UNKNOWN Registry。审查对象包括旧 PLAN.md、budget_model.py、带宽研究文档、两份核心 PDF、关键器件资料和研究目录；网页缓存按用途归类，没有把所有缓存内的每条新闻重新核实一遍。

用户随后确认“3 位初学者、2 位老师、50 天、完整 LM 必须在 FPGA”。因此最终方案收缩到 stories260K，原有 135M/0.5B 全模型部署不再是本期目标。

## 影响决策的修正

| 旧判断/问题 | 核验与修正 | 对计划的影响 |
|---|---|---|
| 默认有 22/32 周，239 人日 | 与用户确认的 50 天不符；学生人数不等于全职工程师人数 | 50 天倒排，D7/14/28 检查，最后 8 天冻结 |
| 0.5B 是唯一适合的量级 | 没有这样的必要条件；小模型可用于完整推理与量化验证 | 选现成 260K，保留更大模型为后续方向 |
| 最小交付删除逐层混合精度 | 会使“使用 KVmix”变成统一低比特量化 | 混合分配、真实 KV 缓存路径和对照实验保留 |
| “embedding/LM head 2-bit 零精度风险” | 查表也有数值误差，输出投影直接影响 token 选择 | 不裁词表、不激进量化 head，先固定 W8 后评估 |
| 缺少 DSP 就做不了所有神经网络 | 逻辑也能做算术；器件适配应按模型、面积、时间判断 | 删除绝对化淘汰规则 |
| PH1P35 没有可用内存 | 指南平台二的示例反而提到片内 DDR；单凭表格遗漏不能排除 | 标记待核对型号/容量/接口，不作为已证实结论 |
| 平台三必然比平台四带宽高 | 板级 DDR 频率标注、PL/PS 路径、控制器效率均需核验 | 按现成例程与实测选择；首版片内存储 |
| 平台三 PCIe 退路按 Gen2 ×4 | 指南物理第 11 页明确 FPGA↔RK3576 为 PCIe2.0×1 | ×1 编码后约 500 MB/s 理论上限，不能按 ×4 估算 |
| “DDR 控制器必须自写”已确认 | UG915 v1.3 的删除记录是历史信息；本地目录快照还有 IPUG035 v1.5、DDR_DualAccess 线索 | 可用性待厂商工程验证；50 天不自写控制器 |
| 1680×20 Kbit 分布式 RAM | 指南表格错位被误读；产品页快照写 1680K，272×20 Kbit 才是 ERAM | 不把分布式 RAM 扩大 20 倍 |
| 小模型分数平坦会导致“全 2-bit” | 固定配额排序仍会选高 bit 层；真正问题是排名是否有预测价值 | 与相同预算的随机分配比较 |
| 换模型只是改配置表 | 参数名、RoPE、缓存接口、维度及算子限制均可能不同 | 只做一个固定 checkpoint；列出适配点 |
| “8 倍缓存 = 8 倍上下文” | 忽略元数据、FP16 尾部、对齐、其他内存以及原生上下文限制 | 用实际字节/块数统计，不外推上下文质量 |
| “带宽是唯一瓶颈”“算力过剩” | 理想 DSP 乘加率并不等于定点化、softmax、控制和访存的实际表现 | 不承诺 tok/s；对整模型计周期 |
| GPU 的 5.3× 可作 FPGA 目标 | 论文改变可容纳 batch，小 FPGA 的模型、内存层级均不同 | 同一板同长度同频率比较，不预设胜负 |
| 给其他赛题的必做项套上本项目 | 选题五只给自主命题综合评价描述 | 完整交付标准是本项目制定的，不声称是赛题原文 |

## 算法与计算模型中的具体错误

1. **Key 分组轴写错。** K 按通道时，同一通道沿 token 轴分组；不是把 head_dim 当作 K 分组长度。V 按 token，沿通道轴分组。新版预算独立处理两者。
2. **分组反量化被错误简化为全局常数。** K 的 scale/min 至少依赖 token 组；V 的 scale/min 依赖通道组。代数折叠只能在对应组内使用，不能对全部上下文复用一次缩放。
3. **3-bit 打包描述自相矛盾。** 论文 10×3+1×2 正好 32 bit，没有因此跨 int32 边界；普通连续 3-bit 流才可能跨字。把论文块说成跨字并额外安排复杂状态机不准确。旧文还把 11 元素/int32 写成了 34.375 元素/字，单位错误。
4. **RPC 被简化成“全历史最近 r%”。** 上游使用当前 FP16 尾部加新 token 的长度，再按组迁移；尾部有取整效应，K/V 不一定相同。预算快照不等于完整动态峰值。
5. **忽略源码与论文参数不同。** 2026-09-21 查看上游 profiler 的尾部比例表，与论文主实验的高/低位宽 20%/10% 不同；Llama 路径对 K3 设 group=11。复现实验应固定 commit 与显式配置。
6. **attention MAC 重复乘了 2。** QK 与 PV 合计为 2×层数×Q头数×头维度×长度个 MAC；1 MAC 对应 2 FLOPs。旧脚本把 MAC/FLOP 的系数又重复算了一次。
7. **权重存储量与每 token 读取量混用。** embedding 输入只读一行，输出投影要读整矩阵；共享权重只计一份驻留。不能说每次生成 embedding 表与 head 都完整读一遍。新脚本如输出读带宽上限，会公开理想读图像假设。
8. **容量预算缺项。** 旧脚本不计 scale/min、残差和 padding；片内 RAM 表还把不同块尺寸的备选缓冲一起相加，正文表格合计与条目不符。新脚本按一个布局计算，并把权重附加空间、工作区写成待替换假设。
9. **模型参数公式不通用。** 旧脚本给 Pythia 也套 SwiGLU 三矩阵 FFN，不适合其结构。新版只保留已核对结构的候选，不继续给所有模型一个“通用”总数。
10. **固定 92% 容量线被说成数学证明。** 235.6 MiB 小于 256 MiB，本身不能证明绝对装不下；要加上工作区、KV 和量化元数据。本期通过小模型留余量解决。

## 为什么改用 stories260K

作者提供现成小词表模型和 tokenizer，具有完整注意力/FFN/归一化等结构，适合验证完整生成；5 层还能做独立 K/V 混合分配。W8 权重约 254 KiB，256 token FP16 KV 为 160 KiB，首版有机会不依赖外部 DDR。

代价也明确：生成能力低，不能外推为通用 LLM 效果；只有 5 层，选层差异可能小；8 维 Value 小组的元数据比例较高；片内缓存压缩未必加速。验收重点是完整硬件链路、实际测量和精度/空间权衡，不是宣称复现论文速度。

这是一项有依据的推荐，**尚未运行权重、尚未测出量化后质量、尚未综合 RTL**。只有 D7 的软件实验和 D14 的数值/资源检查通过后，可行性才从纸面估算推进到实现证据。

## 证据与版本

| 证据 | 位置与用途 |
|---|---|
| 用户赛题 PDF | 根目录 [安路科技]选题指南.pdf；物理页 10～12、33～35；印刷页码有重复“7”，故用物理页码 |
| 用户论文 | 根目录 KVmix-arxiv.pdf；方法部分、Fig.4、Table 3、Fig.7/8；论文结果只作背景 |
| 原计划/计算 | archive/2026-09-21/PLAN.original.md、budget_model.original.py；保留原始哈希 |
| DDR 历史手册 | references/hardware/UG915_PH1A_DDR_old.pdf，v1.3/2023-02；历史限制不是 2026 年可用性结论 |
| DDR 更新线索 | references/evidence/ddr_ip_catalog_snapshot.json；已有本地抓取快照，尚未下载验证 IP 正文和板级工程 |
| PH1A 资源 | references/hardware/DS900_PH1A_Datasheet.pdf 与 references/evidence/ph1a_product_snapshot.txt |

本次在线检查：[KVmix](https://github.com/LfLab-AI/KVmix)、[梯度代码](https://github.com/LfLab-AI/KVmix/blob/main/myprofileKV.py)、[缓存代码](https://github.com/LfLab-AI/KVmix/blob/main/models/modeling_llama_KVmix.py)、[Tiny 模型配置说明](https://huggingface.co/karpathy/tinyllamas/blob/main/stories260K/readme.md)、[Python 结构](https://github.com/karpathy/llama2.c/blob/master/model.py)、[SmolLM2 配置](https://huggingface.co/HuggingFaceTB/SmolLM2-135M/blob/main/config.json)、[Qwen 配置](https://huggingface.co/Qwen/Qwen2.5-0.5B/blob/main/config.json)。网页是查看时的状态，正式实验还需固定 revision。

关于 AMD 参赛资格，本次未找到明确允许纯 AMD 作品参加安路选题五的官方条款；也不据此断言禁止。团队定板前确认，文档没有替组委会作许可决定。

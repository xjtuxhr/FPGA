# 项目条件与验收状态

以实际日志更新。最后整理：2026-09-23。不得把计划中的任务直接勾成已完成。

开放技术问题只维护在 [UNKNOWN Registry](UNKNOWNS.md)；计算公式、条件和候选数据流见 [计算架构](COMPUTE_ARCHITECTURE.md)。本文件只记录已核实的项目决定、纸面推导与实际进度。

## 已确认条件

| 项目 | 状态 |
|---|---|
| 学生 | 3 人，均为初学者 |
| 指导 | 2 位老师：一位研究 KVmix，一位有 FPGA 开发经验 |
| 时间 | 用户确认距提交约 50 天；具体截止日期待填，不用旧文档的 3～8 月 |
| 板卡 | 已确定：安路 MLK-AFH03，FPGA 为 PH1A90；板级例程、工具版本与到位时间待记录 |
| 交付边界 | 完整 LM 在 FPGA 计算；CPU 仅分词/控制；不自动降级为异构注意力加速器 |
| 当前冻结目标 | stories15M、W8、FPGA DDR3L 保存权重和完整 KV Cache、ERAM 保存工作 tile、总长度 ≤256、B/U/M 对照；U 全部 token K2/V2，无 FP16 tail |
| 当前实现 | 已有修订计划与预算脚本；尚无模型运行/RTL/板上实验成果 |

## MODEL / COMPUTE / MEMORY 的当前证据等级

| 类别 | 已确认或可推导内容 | 证据与边界 |
|---|---|---|
| MODEL（项目冻结目标） | stories15M：6 blocks、hidden=288、Q/KV heads=6/6、head_dim=48、FFN=768、vocab=32000、长度 ≤256 | [PLAN](../PLAN.md)；实际 checkpoint header/hash 仍待 MODEL-001/002 |
| COMPUTE（数学推导） | batch=1 decode 的线性层为 GEMV；LM Head=`288×32000=9,216,000` MAC/token；总计 `15,187,968+3,456T` MAC，T=32–256 时约 15.30–16.07 M | [计算架构公式](COMPUTE_ARCHITECTURE.md)；T 含当前 token，不含非线性/访存等待 |
| MEMORY（有条件下界） | 无跨 token 大规模权重缓存时，W8 主矩阵 + LM Head + 当前 embedding row 读取 `15,188,256 B ≈14.49 MiB/token`；ERAM 名义约 680 KiB，不能容纳完整权重 | [计算架构公式](COMPUTE_ARCHITECTURE.md)；不含 scale/对齐/KV/重读，DDR 带宽未测 |
| ARCHITECTURE（方向） | 一套主要计算单元逐层复用为 PLAN 决定；共享 W8 GEMV engine 是候选实现；lane 数、tile、banking、双缓冲均未冻结 | [PLAN](../PLAN.md) 与 [计算架构](COMPUTE_ARCHITECTURE.md) |
| 当前阻塞 | DDR 板级有效带宽未测；DSP 映射和数值格式未定 | [DDR-003、GEMV-001、NUM 项](UNKNOWNS.md) |

上述数字是纸面预算，**不是**已达到的板上吞吐或已通过的模型正确性。

## 开工时填写（由团队完成）

| 待确认事项 | 负责人 | 最晚何时 | 结果/证据位置 |
|---|---|---|---|
| 精确截止日期、比赛届次 | C/指导老师 | D1 | 待填 |
| 板卡原理图、约束、JTAG/UART/ERAM 最小工程 | B/FPGA 老师 | D1～3 | 向安路 FAE 获取并实际跑通；技术细项见 UNKNOWN Registry |
| A 软件、B 硬件、C 集成的姓名 | 全体 | D1 | 待填 |
| 每人每天实际可投入小时 | 全体 | D1，D7 复核 | 待填 |
| 实物板卡型号、到位时间、下载器/电源 | B/FPGA 老师 | D3 | 待填 |
| 工具版本、许可证、RAM/串口示例 | B/FPGA 老师 | D3 | 待填 |
| RTL 或老师已有 HLS 路线 | B/FPGA 老师 | D3 | 待填；不同时开发两条路线 |
| 模型/数值/DDR/KV/host 的技术待确认项 | 对应负责人 | 按阶段 | 统一在 [UNKNOWN Registry](UNKNOWNS.md) 中记录证据，不在此复制第二份清单 |

## 里程碑

- [ ] D3：板卡/资格/工具路线可继续。
- [ ] D7：软件原模型、梯度/量化初测，硬件 RAM/GEMV 正确。
- [ ] D14：必需算子实现与存储资源有证据。
- [ ] D21：单层基线硬件对拍通过。
- [ ] D28：完整基线 B 在 FPGA 生成 32 token。
- [ ] D35：完整 B/U/M 三模式均可运行。
- [ ] D42：质量、速度、缓存、资源、报告初稿完成。
- [ ] D50：干净重建、演示、提交完成。

每次检查记录：日期、实际完成项、证据文件、失败原因、下一步负责人。没有测量就填“未测”，不要补估计值当结果。

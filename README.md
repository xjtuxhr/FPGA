# KVmix_on_FPGA

更新：2026-10-18。**正式模型：HuggingFaceTB/SmolLM-135M；正式架构：方案 C。** B 模式 Attention + DDR 已完成真实模型 CPU/HF 单层对拍、30 层不同 K/V 隔离及非空缓存 RESET 实板验证。下一步接入实际 RK/NPU QKV，并解决 H2C deadline / 故障恢复门槛；完整异构模型与 U/M 尚未验收。详见[当前进度与团队分工](docs/TEAM_PROGRESS_AND_NEXT_STEPS_20261018.md)。

```text
PC：离线重要性分析 / reference / 开发工具 / 用户终端
RK3576 CPU：tokenizer / sampling / 控制 / tensor orchestration / 轻量算子
RK3576 NPU：QKV / O / MLP / LM Head，权重常驻RK LPDDR4X
  ↓ 每层Q/K/V，PCIe
PH1A90SEG324：KVmix / KV管理 / QK / softmax / PV / 性能计数
  ↔ FPGA DDR：完整KV + metadata + buffers
  ↑ 每层attention output，PCIe
RK3576：继续下一层 → logits / sampling / detokenizer → 用户文字
```

RK侧4GB LPDDR4X与FPGA侧256 MiB DDR是不同存储域。FPGA不默认存完整模型权重；不走PCIe持续权重流送。ERAM名义680 KiB，约204 KiB工作集只是早期候选预算；当前联合功能工程使用98/272 ERAM、4/240 DSP，仍有disRAM占用，“不用disRAM”的目标尚未达到。

当前关键工作：**PC1 导出真实 NPU post-RoPE QKV并接host → PC2 统一传输能力声明与超时/恢复证据 → B 重算参考并复核单层对拍 → 真实30层B → U/M集成与质量/性能对照**。当前功能bit为B/MAX_T64/SCORE_SHIFT3；对应功能RTL/TD和新工具仍以本地交付包为主，详见进度文档中的版本与材料索引。stories15M/42M/70M保留为参考/单元验证。

阅读顺序：

先读：[当前进度与团队下一步分工（2026-10-18）](docs/TEAM_PROGRESS_AND_NEXT_STEPS_20261018.md)，包含已验证范围、当前bit身份、PC1/PC2/B工作表及验收顺序。以下早期文档中的进度描述需结合这份新快照阅读。

1. [STARTUP_CHECKLIST](STARTUP_CHECKLIST.md)：已验证的 RK3576 串口/SSH 恢复步骤。
2. [PLAN](PLAN.md)：冻结边界、三人分工、里程碑。
3. [PROJECT_STATUS](docs/PROJECT_STATUS.md)：早期已证事实与进度记录；最新阶段见上面的10-18快照。
4. [COMPUTE_ARCHITECTURE](docs/COMPUTE_ARCHITECTURE.md)：计算与数据流。
5. [UNKNOWNS](docs/UNKNOWNS.md)：唯一开放问题清单。
6. [RK3576 Linux / NPU / PCIe 开发入口](docs/RK3576_LINUX_DEVELOPMENT.md)：随板教程证据、版本矩阵与操作 SOP；教程称出厂默认 Buildroot，**本项目实板已运行 Debian 12**。
7. [预算说明](docs/BUDGET_GUIDE.md)、[模型与PC证据](docs/MODEL_AND_PC_RESULTS.md)、[硬件事实](docs/HARDWARE_FACTS.md)。
8. [REVIEW](docs/REVIEW.md)：历史判断修正；[原始资料索引](references/README.md)。
9. [Hummingbird+ 论文启发与实施建议（2026-10-16）](docs/HUMMINGBIRD_PLUS_PROJECT_INSIGHTS_20261016.md)：GQA 复用、DDR 分块、softmax 和 KVmix 融合的候选优化及对照实验；区分论文报告、本地构建证据与待实测结果。
10. [Attention + DDR 单层对拍交接（更新 2026-10-16）](docs/ATTENTION_DDR_BOARD_HANDOFF_20261014.md)：历史操作包、bit SHA256、COM4 DDR就绪结果及回传条件。后续单层实板对拍与隔离/RESET已通过；以10-18快照的结果和接入门槛为准，操作包由B另行交付。

```powershell
python tools/budget_check.py --model smol135m
python tools/budget_check.py --self-test
```

预算脚本与大型模型、PC原始报告、随板教程目前未纳入此 Git 仓库；上述命令仅供持有本地脚本的成员使用，文档中的公式和结果可单独阅读。脚本默认heterogeneous_c；full_fpga仅历史比较。B=FP16 KV存储，U=全层全token K2/V2无tail，M=layer-aware mixed + recent FP16 tail；三组共享RK计算、权重、接口、FPGA Attention算术和评测设置。容量通过不等于NPU/PCIe/数值/综合验收通过。

历史入口：[旧计划](PLAN_FULL_FPGA_HISTORY.md)、[旧计算架构](docs/COMPUTE_ARCHITECTURE_FULL_FPGA_HISTORY.md)、[旧预算说明](docs/BUDGET_FULL_FPGA_HISTORY.md)。其SUPERSEDED/HISTORICAL内容不指导当前开发。

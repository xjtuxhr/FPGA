# KVmix_on_FPGA

更新：2026-09-30。**正式模型：HuggingFaceTB/SmolLM-135M；正式架构：方案 C。** RK3576 已由成员通过串口和 SSH 登录 Debian 12；NPU、PCIe 与完整模型尚未跑通。

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

RK侧4GB LPDDR4X与FPGA侧256 MiB DDR是不同存储域。FPGA不默认存完整模型权重；不走PCIe持续权重流送。ERAM名义680 KiB，目标不用disRAM，约204 KiB工作集只是候选预算。

当前关键工作：**NPU实际shape/M=1 benchmark → PCIe小tensor往返测量 → Attention-only FPGA bring-up**，不是完整Transformer RTL。stories15M/42M/70M保留为参考/单元验证，不主导完整上板验收。

阅读顺序：

1. [STARTUP_CHECKLIST](STARTUP_CHECKLIST.md)：已验证的 RK3576 串口/SSH 恢复步骤。
2. [PLAN](PLAN.md)：冻结边界、三人分工、里程碑。
3. [PROJECT_STATUS](docs/PROJECT_STATUS.md)：已证事实与当前进度。
4. [COMPUTE_ARCHITECTURE](docs/COMPUTE_ARCHITECTURE.md)：计算与数据流。
5. [UNKNOWNS](docs/UNKNOWNS.md)：唯一开放问题清单。
6. [RK3576 Linux / NPU / PCIe 开发入口](docs/RK3576_LINUX_DEVELOPMENT.md)：随板教程证据、版本矩阵与操作 SOP；教程称出厂默认 Buildroot，**本项目实板已运行 Debian 12**。
7. [预算说明](docs/BUDGET_GUIDE.md)、[模型与PC证据](docs/MODEL_AND_PC_RESULTS.md)、[硬件事实](docs/HARDWARE_FACTS.md)。
8. [REVIEW](docs/REVIEW.md)：历史判断修正；[原始资料索引](references/README.md)。

```powershell
python tools/budget_check.py --model smol135m
python tools/budget_check.py --self-test
```

预算脚本与大型模型、PC原始报告、随板教程目前未纳入此 Git 仓库；上述命令仅供持有本地脚本的成员使用，文档中的公式和结果可单独阅读。脚本默认heterogeneous_c；full_fpga仅历史比较。B=FP16 KV存储，U=全层全token K2/V2无tail，M=layer-aware mixed + recent FP16 tail；三组共享RK计算、权重、接口、FPGA Attention算术和评测设置。容量通过不等于NPU/PCIe/数值/综合验收通过。

历史入口：[旧计划](PLAN_FULL_FPGA_HISTORY.md)、[旧计算架构](docs/COMPUTE_ARCHITECTURE_FULL_FPGA_HISTORY.md)、[旧预算说明](docs/BUDGET_FULL_FPGA_HISTORY.md)。其SUPERSEDED/HISTORICAL内容不指导当前开发。

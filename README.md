# KVmix on FPGA

目标：用完整轻量语言模型在 FPGA 上生成文字，比较普通 KV 缓存与 KVmix 混合精度缓存。当前条件：3 位初学者、2 位指导老师、约 50 天；已确定使用安路 MLK-AFH03（PH1A90）。

**从 [PLAN.md](PLAN.md) 开始。** 当前主线是现成 stories15M 模型；层重要性分析在电脑离线完成，完整 Transformer 推理和 KVmix 留在 FPGA，DDR 保存权重和完整 KV Cache。stories260K 仅用于最早期算子联调。

| 需要什么 | 打开哪里 |
|---|---|
| 现在做什么、用什么工具、50 天怎么排 | [PLAN.md](PLAN.md) 第 4～5、8 节 |
| 填人员、板卡、期限和进度 | [项目状态](docs/PROJECT_STATUS.md) |
| 查 stories15M 计算图、MAC/DDR 公式及未冻结设计候选 | [计算架构](docs/COMPUTE_ARCHITECTURE.md) |
| 查尚缺什么证据、何时必须确认 | [UNKNOWN Registry](docs/UNKNOWNS.md) |
| 为什么推翻旧计划的一些结论 | [审查记录](docs/REVIEW.md) |
| 找原论文/赛题 | 根目录的 KVmix-arxiv.pdf、[安路科技]选题指南.pdf |
| 查 RAM、DSP 等手册 | [资料索引](references/README.md) |
| 找旧版、重复研究、网页缓存 | [归档说明](archive/2026-09-21/README.md) |

当前可运行的是预算计算，尚无完整模型软件/RTL 实现：

```powershell
python tools/budget_check.py --self-test
python tools/budget_check.py --model stories15m --contexts 64 128 256
```

预算含明确假设，不代表板上实测。`budget_model.py` 保留为上述工具的兼容入口。新写的开发代码、日志以后分别放 software/、rtl/、sim/、host/、results/；计划中列出的文件名均为待开发产物。

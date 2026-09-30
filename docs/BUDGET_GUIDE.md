# 预算工具：方案C与历史全FPGA

更新：2026-09-30。`tools/budget_check.py` 当前只在本地工作区，**未随 Git 文档上传**；下列命令供已取得脚本的成员复算，文中的预算表可独立阅读。脚本仅用标准库，不加载模型或修改输入；默认heterogeneous_c，省略模型时交互选择，批处理须--model；正式目标smol135m，其他六模型保留。

```powershell
python tools/budget_check.py --list-models
python tools/budget_check.py --model smol135m --contexts 64 128 256
python tools/budget_check.py --model smol135m --weight-bits 16 --tensor-bits 16
python tools/budget_check.py --self-test
# 仅历史架构
python tools/budget_check.py --architecture full_fpga --model smol135m --verdict-only
```

当前分支：

- RK内存=参数×weight-bits+weight-metadata-mib；rk-memory-mib默认4096是名义总容量，未计OS/NPU workspace/布局副本。W8存储场景不是冻结NPUdtype。
- FPGA DDR=完整KV（含metadata）+ddr-buffer-mib（候选1）。
- FPGA ERAM=attention-workspace-kib（候选140）+other-eram-reserve-kib（候选64）=204KiB，不计旧weight tile/logits。无disRAM预算不证明综合不会用disRAM。
- RK linear与FPGA QK/PV MAC分列。U/M不减少QK/PV MAC，新增quant/dequant资源/timing未知。
- PCIe每层QKV+attention output，tensor-bits16仅容量假设，Smol92160B/token、30次交互；不由峰值推吞吐。

| T256模式 | KV MiB（已含metadata） | FPGA DDR加1MiB |
|---|---:|---:|
| B/fp16 | 5.625000 | 6.625000 |
| U/int2 | 1.054688 | 2.054688 |
| M/mixed | 1.672119 | 2.672119 |

所列容量通过，系统可运行性UNKNOWN：NPU shape/M=1、copy/sync、PCIe latency、Attention数值/综合必须测。不把旧“FP16权重放不进FPGA256MiB”套方案C。

可调整rk-memory-mib、ddr-buffer-mib、attention-workspace-kib、other-eram-reserve-kib、tensor-bits、context/KV布局。group32、重要层3、tail32、metadata4B、dense K3为候选，真实层ID由PC产生。cuda11需K3 group11，不自动复现PC质量。

140+64KiB候选针对当前Smol/T≤256分析，不随模型/context自动调整；计算其他模型或更长context必须重新核对working-set，不能把固定候选当作自动资源估值。

full_fpga的workspace/weight tile/KV buffer/logits及lane/DSP/速度参数不作用于当前分支；仅显式历史调用。--verdict-only在方案C仍输出分域容量与必要UNKNOWN，无综合承诺。

旧说明见 [BUDGET_FULL_FPGA_HISTORY](BUDGET_FULL_FPGA_HISTORY.md)，硬件依据 [HARDWARE_FACTS](HARDWARE_FACTS.md)，问题统一 [UNKNOWNS](UNKNOWNS.md)。

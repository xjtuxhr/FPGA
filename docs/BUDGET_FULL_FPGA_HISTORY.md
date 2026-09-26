# REFERENCE ONLY：全 FPGA 预算说明

以下数字和命令只适用于历史全 FPGA 架构。运行命令必须添加 `--architecture full_fpga`，否则新脚本默认方案 C；当前说明见 [BUDGET_GUIDE](BUDGET_GUIDE.md)。旧“Smol容量/ERAM不通过”不能直接套用异构主线。

更新：2026-09-26。入口是 `tools/budget_check.py`，只用Python标准库，不加载PyTorch/权重，不修改输入文件。不代表板上资源/吞吐，不预测PPL。

硬件口径为 [PH1A90SEG324](HARDWARE_FACTS.md)：240 DSP、5440K ERAM沿用680 KiB预算；此次截图校正不改变脚本默认容量。DDR规格1066 Mbps/x16的条件理论上限为2.132 GB/s，不是实测值，不能直接作为 `--bandwidth-gbps` 的板上证据。256 MiB外部DDR容量是独立板级预算，不由截图确认。分布式RAM不未经映射验证就加入ERAM预算。

## 1. 最简单的使用方式

在项目根目录的真实终端运行：

```powershell
python tools/budget_check.py --architecture full_fpga
```

先输入模型编号或名称，再开始预算。可选stories260k、stories15m、stories42m、stories110m、smol135m、smol2_70m、qwen05；错误输入会重问，q退出。批处理/重定向stdin时必须指定模型，不悄悄选择15M：

```powershell
python tools/budget_check.py --architecture full_fpga --list-models
python tools/budget_check.py --architecture full_fpga --self-test
python tools/budget_check.py --architecture full_fpga --model smol135m --contexts 64 128 256
python tools/budget_check.py --architecture full_fpga --model smol135m --contexts 256 --weight-bits 16
python tools/budget_check.py --architecture full_fpga --model smol2_70m --contexts 64 128 256
python tools/budget_check.py --architecture full_fpga --model smol2_70m --contexts 256 --weight-tile-kib 64 --verdict-only
```

旧 `--model stories15m` 等CLI仍有效；`kv_bytes`/`attention_macs`函数仍存在。M默认重要层比例从旧20%向上取整改为报告的10%向下取整、非零至少1层。复现旧15M的2重要层表格用 `--important-layers 2`（只改比例20%不保证旧向上取整行为）。int4保留辅助场景的tail假设，需 `--modes fp16 int2 mixed int4` 才输出。

70M入口`smol2_70m`对应codelion/SmolLM2-70M的实际config/header：32层、D384、FFN1024、Q/KV6/2、HD64、V49152、T8192、69,230,976参数。默认buffer和4 MiB附加保持与Smol135M一致，故默认ERAM预留仍失败；不是模型变小就自动缩buffer。64 KiB候选tile可使576+64=640 KiB通过680 KiB容量预算，仍需综合。完整数字、下载版本和哈希见 [70M预算](SMOLLM2_70M_BUDGET.md)，不能将Smol135M的PC效果外推到它。

## 2. 不能混用的三种“精度”

| 参数/模式 | 控制什么 | 不控制什么 |
|---|---|---|
| `--weight-bits 8`（默认） | 全部参数裸容量/主矩阵读字节的W8近似 | 不把activation/accumulator/非线性冻结成8-bit |
| fp16 / int2 / mixed | B FP16 KV；U K2/V2无tail；M重要层K3/V4、其他K2/V2+tail | 不把权重变成2-bit；不改变Transformer形状/MAC |
| `--logit-bits 32`（默认） | logits完整buffer/返回容量 | 不是已冻结的logits数值格式 |

当前FPGA路线B/U/M共用定点Attention。若未来采用直接低bit/fused KV arithmetic，DSP映射、scale重用、算术量须重新综合/对拍；本脚本**不虚构“FP16→2bit自动节省8倍DSP”**。全W16也不意味着脚本预算了FP16浮点单元。

Smol本地实际是F32 safetensors，config声明BF16；报告FP16指PC评测设置。[模型事实](MODEL_AND_PC_RESULTS.md)已记录差异。

## 3. 每列表示什么

- `KV MiB`：payload+32-bit独立分组padding+FP16尾部+metadata；不是只有bit数÷8。
- `meta MiB`：KV scale/min等附加空间；默认每压缩组4 B。
- `DDR MiB`：裸权重+用户附加权重预算+完整KV，**未包含真实地址图的其他DDR分配**。全部norm也按weight-bits计裸容量是近似；高精度参数、头部、scale、对齐等应填入附加预算。
- `MAC M`：所有线性矩阵+完整LM Head+QK/PV；不含norm、softmax、RoPE、SiLU、偏置add、控制与转换。B/U/M相同。
- `read MiB`：主矩阵+head+当前embedding一行+全量附加权重预算+KV扫描；不是权重驻留容量，也不是总读写。
- `FP16转换M`、`反量化M`：扫描中对应元素数量。反量化候选 `x=q*scale+min` 为每元素1乘+1加，外加bit extraction；FP16需转共同定点格式。
- `组数`/`32bit解包字`：读取metadata/packed payload的工作量；不自动等于cycle/LUT。
- `本步量化/重算候选元素`：U假设每次把当前未满K组重新min/max、量化，加新V；M按本步tail退出及K组齐组迁移计，不是每token均值，组边界会尖峰。B为0。需另实现并测量归约/scale/打包/迁移读写，不能把它当已验证协议。

GQA的QK/PV MAC用**Q头数**；KV存储/转换用**KV头数**。默认 `--kv-read-passes 1` 假设K/V可在共享Q头间复用；不能复用时Smol可用3遍保守扫描场景，但并非数学必需。遍数不改变模型MAC。

## 4. 量化布局参数：预算候选，不是协议冻结

```powershell
python tools/budget_check.py --architecture full_fpga --model smol135m --important-layers 3 --residual 32 --k-group-size 32 --v-group-size 32
python tools/budget_check.py --architecture full_fpga --model smol135m --k3-packing cuda11 --k3-group-size 11
python tools/budget_check.py --architecture full_fpga --model stories15m --k-group-size 16 --v-group-size 16
```

K沿token轴每KV通道分组，V沿channel轴每head/token分组。M的旧K不满组仍留FP16，实际FP16量可能超过显式tail。U没有任何FP16 tail，其未满K组压缩+计metadata。

`--important-fraction`与`--important-layers`互斥；fraction0可做全低bit带tail消融。K/V高精度组各取相同层数，真实层ID可不同；需预算不同数量时当前工具尚未支持独立K/V配额。`--kv-metadata-bytes`、`--k3-group-size`可显式改。dense模式3-bit全部足位；cuda11有每字第11元素2-bit损失和group11附加成本，二者不可拿同PPL解释。

## 5. Smol默认可复算数字（DERIVED）

前提：W8、4 MiB权重附加预算、重要K/V层各3/30、tail32、K/V/K3 group32、dense、metadata4 B、KV一次扫描。MiB=2^20 B。

| T | B KV MiB | U KV MiB | M KV MiB | B/U/M相同模型MAC M |
|---:|---:|---:|---:|---:|
| 64 | 1.406250 | 0.263672 | 0.841553 | 136.691712 |
| 128 | 2.812500 | 0.527344 | 1.118408 | 138.903552 |
| 256 | 5.625000 | 1.054688 | 1.672119 | 143.327232 |

T256：W8裸权重128.283508 MiB；B/U/M DDR总预算137.908508/133.338196/133.955627 MiB。一遍权重主矩阵扫描128.250549 MiB（未计附加量）；主要成本不因KV压缩消失。全W16裸权重256.567017 MiB >256 MiB，三种Cache都不能修复权重容量超限。

ERAM默认激活/控制256+weight tile128+KV buffer64+完整32-bit logits192=640 KiB，相对680仅留40 KiB；DDR IP/FIFO/额外量化流水线还未计，**不是实际可布局证明**。logits=49,152×4=196,608 B；16-bit为96 KiB，8-bit为48 KiB。减位宽/分块输出需先做数值与接口验证，不能为省容量直接冻结。

## 6. 可选计算周期/资源与带宽场景

以下只是说明如何填参数，1 GB/s、16 lane、100 MHz、1 DSP/lane不是实测或建议冻结值：

```powershell
python tools/budget_check.py --architecture full_fpga --model smol135m --contexts 256 --bandwidth-gbps 1 --lanes 16 --clock-mhz 100 --dsp-per-lane 1 --fp16-convert-elements-per-cycle 8 --dequant-elements-per-cycle 8 --quant-elements-per-cycle 4
```

模型MAC理想周期=`ceil(MAC/(lanes*MAC_per_lane_cycle))`；候选MAC DSP=`lanes*DSP_per_lane`，没有提供综合映射就保持UNKNOWN。新增量化/解包/非线性资源不从此公式扣除。转换候选串行周期=FP16元素/转换率+压缩元素/反量化率+本步量化元素/量化率（各向上取整）；不够速率证据就不输出完整转换周期。

理想DDR read-only tok/s=`有效GB/s*10^9/read_bytes`，不含写入、KV迁移、重读、PCIe/logits或非线性。提供多项时输出完美重叠乐观上限=`1/max(各已建模秒数)`；实际可能串行、相互争用，不能做完成承诺。示例T256 B/U/M读上限约6.917/7.154/7.121 tok/s：即使KV大幅压缩，总权重流量仍占主导。

低bit KV确实会显著改变缓存/访存与额外逻辑；“DSP面积一定显著下降”和“整机一定显著加速”仍无证据。最终分别记录统一可重配置top的资源、各专用top的综合资源（若存在）、同频率runtime计数，不把运行模式切换误写为芯片物理资源变小。

## 7. 先给结论：计算资源能否支持上板

上一版只列预算，未汇总结论，已修正。每次预算开始先输出上板判定；只看结论用：

```powershell
python tools/budget_check.py --architecture full_fpga --model smol135m --contexts 256 --verdict-only
```

必须区分两个问题：**原始FP16权重/FP16算术**与**项目W8权重+共享定点算术**。KVmix只量化KV；若保持FP16权重，T256的B/U/M最低驻留量262.192/257.622/258.239 MiB，均超过256 MiB。即使KV全部省掉，裸权重256.567 MiB也超限。结论是本项目完整驻留路线不可上板；不泛化到权重外部流式加载/更大DDR等其他架构，也不声称FP16单元面积已计算。

### 默认计算资源场景（全部是可修改假设）

| 输入 | 候选值 | 含义 |
|---|---:|---|
| target-tps | 1 | 用于可行性评估的演示速度，不冻结赛事目标 |
| assessment-clock-mhz | 100 | 无用户clock时的候选频率，不宣称timing达到 |
| assessment-lanes | 16 | 无用户lanes时的共享核候选，不冻结并行度 |
| assessment-dsp-per-lane | 2 | 无实测映射时的敏感性假设；同时展示1/2/4 DSP场景 |
| mac-utilization | 0.25 | MAC阶段有效利用率假设，不含非线性/转换端到端吞吐 |
| other-dsp-reserve | 32 | 非MAC资源预留，不是量化实际DSP需求 |
| other-eram-reserve-kib | 64 | IP/FIFO/额外逻辑预留，不是DDR IP实测面积 |

用户的 `--clock-mhz/--lanes/--dsp-per-lane` 优先覆盖对应评估候选。默认利用率只用于可行性判断；旧详细表的MAC-only ceiling仍为理想满利用率，两者口径不能混淆。

Smol T256需要143.327M模型MAC/token。上述16 lane场景用32 DSP，含预留64/240，MAC阶段约2.791 tok/s；若只按1 tok/s的MAC目标，至少6 lane、含预留44 DSP。**结论：W8 B/U/M没有因参数量135M而被MAC核心资源淘汰；计算部分估算有条件可行。** 逐层复用使面积依赖并行度/位宽而不是为每个模型MAC安装一个乘法器；层数与权重增大主要增加执行时间与数据调度工作。

但是默认ERAM=640+64预留=704 KiB >680，三模式的**当前缓冲/预留方案不通过**。这是方案层面的失败，不是Smol模型永远无法上板。保留完整32-bit logits的情况下，可只把候选weight tile从128减至64 KiB重新评估：

```powershell
python tools/budget_check.py --architecture full_fpga --model smol135m --contexts 256 --weight-tile-kib 64 --verdict-only
```

此时ERAM576+64=640 KiB、DSP和DDR候选预算通过，脚本输出“估算有条件可上板”。它不证明64 KiB tile的banking/burst效率，仍需实际测试。不能靠盲减数值精度或虚减IP预留制造通过。

### 判定等级

- **不可按当前容量方案上板**：已列权重/KV或工作缓冲超出硬容量预算。
- **当前预算方案不通过；需调整后重算**：计入候选预留超资源、所选lane不足、总可用DSP不足以达到目标、给定DDR带宽不足，或给定转换速率的单阶段已超过token时间。逐项显示原因；候选条件失败不冒充实测失败。
- **估算有条件可上板**：已建模预算未发现超限，不等于LUT/DFF、非线性/量化流水线、DDR写放大、时序和数值均验收通过。

达到1 tok/s的必要读取下限约B 0.145、U 0.140、M 0.140 GB/s；是读下限不是整机充足条件。提高目标需重算，例如10 tok/s至少58个候选lane/含预留148 DSP，默认16lane达不到，且若实测DDR仅1 GB/s，读取也达不到10 tok/s。U/M降低KV空间并增加转换/迁移逻辑，不自动减少核心MAC需求。

## 8. 限制和同步

PPL、LUT/DFF、ERAM分配、DDR写放大、量化流水线资源、GQA复用和clock timing都需实验。PC报告不是这些输入的替代品；开放问题见 [Registry](UNKNOWNS.md)。

当前 `.gitignore` 忽略tools目录；本轮只更新脚本和Markdown，未改Git配置、未提交/push。队友同步脚本需另行授权将其纳入版本控制或直接分发。

本轮验证：self-test通过；六模型CLI；模拟终端的错误输入/编号/名称；7种非法参数/非交互输入；本地Smol config与safetensors shape/参数独立交叉检查；1,632种layout元素/字节恒等式；cuda11、GQA三遍读取、W16超限、DSP超限、旧15M两重要层数值回归；Python语法、Markdown本地链接和git diff --check。所有测试用 `-B` 禁止生成pycache，未创建正式模型/RTL/host代码。

# FPGA 算子库：KVmix 量化 + Attention（PH1A90SEG324）

方案 C 中 FPGA 侧（PH1A90SEG324）的核心算子库：**KVmix 混合精度量化/反量化 + QK/softmax/PV 注意力**，纯 Verilog-2001，已在 iverilog 仿真和安路 TD 综合下验证。

对应团队文档：[PLAN](../PLAN.md)、[COMPUTE_ARCHITECTURE](../docs/COMPUTE_ARCHITECTURE.md)、[UNKNOWNS](../docs/UNKNOWNS.md)。

## 目录

```text
rtl/          算子 Verilog 源码（26 个文件，含综合顶层 + KV 存储/RPC 控制）
sim/          自校验 testbench（iverilog，21 个）
golden/       Python 对拍向量生成器 + 轻量 golden 向量（.hex）
td/           TD 批处理综合脚本
constraints/  板级引脚约束（kv_quant_demo 演示顶层）
docs/         接口需求文档（DDR/量化格式/PCIe，发给队友对齐用）
```

## 定点格式（CANDIDATE，对应 NUM-001/002/003，未冻结）

| 量 | 格式 |
|---|---|
| Q/K/V | Q8.8 有符号（16-bit，值 = int/256） |
| scale | Q0.8 无符号 |
| prob | Q0.16 无符号（值 = int/65536） |
| score | Q16.16（32-bit） |

- 非对称分组量化：`q = clamp(round((x-min)/scale))`，反量化 `x = q*scale+min`。
- Key 按通道（沿 seq 分组）、Value 按 token（沿 head_dim 分组），group_size 32（3-bit 特例 11）。
- 3-bit 打包：11 元素 → 1 个 32-bit 字（10×3-bit + 1×2-bit）。
- exp 用 256 项 LUT（`x∈[-7.97,0]`），除法用恢复余数法（32 拍）。

## 模块

| 模块 | 作用 |
|---|---|
| `kv_quant` / `kv_dequant` | 量化 / 反量化 |
| `min_max_reduce` / `scale_calc` | 分组 min/max、`inv_scale = qmax/(max-min)` |
| `kv_pack_3bit` / `kv_unpack_3bit` | 3-bit 特例打包/解包 |
| `div_u32_u16` / `div_u32_u32` | 32/16、32/32 除法器 |
| `exp_lut` | exp 查找表 |
| `dot_product` / `weighted_sum` | QK 点积 / PV 加权求和 |
| `softmax` | 完整 softmax（max → exp LUT → 归一化除法） |
| `attention` | 单头注意力集成（先存后算） |
| `gqa_attention` | GQA 头复用（`g = h / NGROUPS`，SmolLM-135M：H=9/G=3/D=64） |
| `kv_quant_demo` | 板级演示顶层（量化到 FMC LA 引脚） |
| `kv_ops_top` | 综合冒烟测试顶层（实例化全部算子） |
| `gqa_synth_t64/128/256` | GQA 真实尺寸综合顶层（H=9/G=3/D=64，扫 T） |
| `fp16_to_q88` | FP16 → Q8.8 转换器（NUM-009，组合逻辑，subnormal→0、inf/NaN→饱和） |
| `q88_to_fp16` | Q8.8 → FP16 转换器（`fp16_to_q88` 的逆，NUM-001 占位） |
| `attention_b_top` | Attention-only B 通路顶层（FP16 Q/K/V → Q8.8 → GQA attention） |
| `attention_b_synth` | B 通路综合顶层（真实尺寸） |
| `kv_rpc_ctrl` | RPC tail 管理控制状态机（M 方案：环形窗口 + recent 边界 + requant 命令） |
| `kv_addr_map` | KV cache 在 DDR 的地址映射（data 区 + meta 区，无重叠） |
| `kv_store_fsm` | KV cache 数据通路骨架（BRAM 模拟 DDR：写→requant→读时序） |

## 仿真（iverilog）

testbench 读 `golden/*.hex` 自校验，全部通过。示例：

```bash
cd fpga_kv_attention/sim
iverilog -o gqa_tb gqa_attention_tb.v ../rtl/gqa_attention.v ../rtl/attention.v \
         ../rtl/exp_lut.v ../rtl/div_u32_u32.v
vvp gqa_tb   # gqa_attention: ALL 16 outputs PASSED
```

## 综合（安路 TD）

批处理脚本在 `td/synth_all_ops.tcl`，实例化全部算子做综合冒烟测试（D=8/T=4），TD 下零错误：

```bat
<td_install_dir>\td_commands_prompt.exe fpga_kv_attention/td/synth_all_ops.tcl
```

冒烟测试资源（PH1A90SEG324，D=8/T=4）：LUT 2324、reg 1676、ERAM 2/272、DSP 10/240。

真实尺寸综合（SmolLM-135M：H=9/G=3/D=64，`td/synth_gqa.tcl` + `td/timing.sdc` 25MHz 约束，
顶层 `rtl/gqa_synth_t64/t128/t256.v`）：

| T | ERAM | ERAM% | DSP | LUT | Slice% | dist-RAM(LUT) | Fmax | SWNS |
|---|---|---|---|---|---|---|---|---|
| 64 | 21 | 7.7% | 4 | 3589 | 5.1% | 2128 | 88.7 MHz | +28.7 ns |
| 128 | 41 | 15.1% | 4 | 6458 | 9.7% | 4240 | 83.7 MHz | +28.1 ns |
| 256 | 79 | 29.0% | 4 | 12232 | 18.2% | 8464 | 78.1 MHz | +27.2 ns |

结论：ERAM 随 T 线性增长（T=256 用 29%）、DSP 恒定 4、时序富余（Fmax 78–88 MHz ≫ 25 MHz）。
store-then-compute 架构的 K/V 片内存储是主要资源项，当前存在双重存储（gqa 存全量 + attention 再存单头）
与部分分布式 RAM，后续需优化（见 RTL-001/RTL-002）。

Attention-only B 通路（`td/synth_b.tcl`，含 fp16_to_q88 转换器，D=64/T=64）：LUT 3691、ERAM 21/272、DSP 4/240、Fmax 88.9 MHz（SWNS +28.8ns）。转换器仅 +102 LUT，对时序无影响。

## 验证状态

- 仿真：所有算子 testbench 与 Python 定点对拍 **全部通过**；D=64 GQA 端到端 576 输出、FP16→Q8.8 转换器 249 用例、Q8.8→FP16 转换器 232 用例、Attention-only B 通路端到端 576 输出、RPC tail 控制、KV 地址映射、KV 存储骨架均通过。
- 综合：TD `import_device ph1_90.db -package PH1A90SEG324` 下 `optimize_rtl` + `optimize_gate` 通过，0 错误（D=8 冒烟、D=64 GQA 三档、B 通路均干净）。
- 未做：布局布线（P&R）与 P&R 后时序收敛、板上 DDR/PCIe 接入、真实 quant 接入存储骨架（requant 目前是占位标记）。

# FPGA 算子库：KVmix 量化 + Attention（PH1A90SEG324）

方案 C 中 FPGA 侧（PH1A90SEG324）的核心算子库：**KVmix 混合精度量化/反量化 + QK/softmax/PV 注意力**，纯 Verilog-2001，已在 iverilog 仿真和安路 TD 综合下验证。

对应团队文档：[PLAN](../PLAN.md)、[COMPUTE_ARCHITECTURE](../docs/COMPUTE_ARCHITECTURE.md)、[UNKNOWNS](../docs/UNKNOWNS.md)。

## 目录

```text
rtl/          算子 Verilog 源码（16 个文件）
sim/          自校验 testbench（iverilog，14 个）
golden/       Python 对拍向量生成器 + 轻量 golden 向量（.hex）
td/           TD 批处理综合脚本
constraints/  板级引脚约束（kv_quant_demo 演示顶层）
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
真实尺寸（D=64）的 ERAM/DSP 评估待放大参数后确认；store-then-compute 架构的 K/V 片内存储会随 context 长度 T 线性增长，是主要资源项。

## 验证状态

- 仿真：所有算子 testbench 与 Python 定点对拍 **全部通过**（含 GQA 头复用 16 输出）。
- 综合：TD `import_device ph1_90.db -package PH1A90SEG324` 下 `optimize_rtl` + `optimize_gate` 通过，0 错误。
- 未做：布局布线、时序收敛、板上 DDR/PCIe 接入、RPC tail 管理（M 方案）。

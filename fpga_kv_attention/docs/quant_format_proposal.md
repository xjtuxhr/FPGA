# KVmix 量化格式提案（给 PC1，KV-002 / NUM-001 对齐）

> 本文由 FPGA 侧（B）起草，列出 FPGA 侧已实现的定点格式，请你（PC1，reference/数值）确认或修改后冻结。

## FPGA 侧已实现（CANDIDATE，待对齐后冻结）

| 量 | 格式 |
|---|---|
| Q/K/V（attention 算术） | Q8.8 有符号（16-bit，值 = int/256） |
| scale | Q0.8 无符号 |
| prob | Q0.16 无符号 |
| score | Q16.16（32-bit） |

- 非对称分组量化：`q = clamp(round((x-min)/scale))`，反量化 `x = q*scale + min`；
- **K 按 channel**（沿 seq 分组）、**V 按 token**（沿 head_dim 分组），group_size = 32（3-bit 特例 11）；
- 3-bit：11 元素打包成 1 个 32-bit 字（10×3-bit + 1×2-bit）；
- FP16→Q8.8 转换已实现（`fp16_to_q88`，subnormal→0、inf/NaN→饱和）。

## 需要你明确（KV-002）

1. scale / min 的定点格式与位宽（我用 Q0.8 / Q8.8 作候选）；
2. 每个 group 的 metadata（scale+min）在 DDR 里占几字节、怎么对齐；
3. K3 用 dense 3-bit 还是沿用 11 元素打包（cuda11）；
4. group 轴最终用哪个（上面的 K/V 分组是我的候选）。

## 需要你明确（NUM-001）

1. QKV 从 RK/NPU 经 PCIe 进 FPGA 的 dtype：**FP16** 还是已在 RK 侧转成定点？（若 FP16，FPGA 侧已有转换器）
2. attention output 回传 RK 的 dtype / scale / layout。

## 现状边界

上述格式已在 iverilog 仿真 + Python 定点对拍下验证（D=64 端到端 576 输出、FP16→Q8.8 249 用例、溢出边界 |q|,|k|≤5792）。冻结前不声称数值边界已定。

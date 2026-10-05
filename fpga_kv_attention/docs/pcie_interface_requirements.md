# FPGA 侧 PCIe 接口需求（给 PC2，PCIE-003）

> 本文由 FPGA 侧（B）起草。FPGA endpoint 需要的输入/输出接口，已对应到 `rtl/attention_b_top.v` 的端口。

## FPGA endpoint 需要的输入（每层一次）

| 信号 | 数据 | 说明 |
|---|---|---|
| `start` | 1 bit 脉冲 | 整层开始 |
| `q_valid` + `q_fp16[15:0]` | 9×64 个 FP16 | 查询 Q，流式 |
| `k_valid` + `k_fp16[15:0]` | 3×T×64 个 FP16 | 键 K，流式 |
| `v_valid` + `v_fp16[15:0]` | 3×T×64 个 FP16 | 值 V，流式 |

（顺序与 `attention_b_top` 一致：先 Q，再 K，再 V，各带 valid 握手。）

## FPGA endpoint 的输出（每层一次）

| 信号 | 数据 | 说明 |
|---|---|---|
| `out_valid` + `out[31:0]` + `out_head[7:0]` + `out_d[7:0]` | 9×64 个 | attention 结果，流式 |
| `done` | 1 bit 脉冲 | 整层完成（当前 RTL 尚未加，可补） |

## 需要你明确（PCIE-003）

1. packet / layout / 对齐（32B header？DMA padding？）；
2. 层号 / 位置 / 序列状态、完成标识、错误处理；
3. BAR 地址映射、FPGA 侧收/发 FIFO 深度；
4. 是否沿用 `pcie_contract/contract.json` 的版本机制（我按这个契约提需求，不另起炉灶）。

## 备注

FPGA 侧 RTL 目前是纯逻辑（无 PCIe 物理层），`attention_b_top` 已通过仿真 + TD 综合（D=64/T=64，ERAM 21/272、DSP 4/240、Fmax 88.9MHz）。PCIe 物理 endpoint（SERDES/SGDMA）尚未接，接口对齐后我来写 FPGA 侧 endpoint 适配层。

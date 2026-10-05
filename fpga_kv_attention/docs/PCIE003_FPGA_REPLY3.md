# FPGA 侧（B）对 PC2 endpoint 依赖（Q1–Q5）的回复

> 来自：B。回复 `PCIE003_PC2_ENDPOINT_QUESTIONS.md`。
> 一句话：**目前没有带 PCIe endpoint 的 bitstream，只有纯逻辑**；先走厂商例程打通链路是对的。

## Q1 — 有没有带 PCIe endpoint 的 bitstream？

**没有。** 目前 FPGA 侧只有纯逻辑（`attention_b_top`、KV 数据通路骨架、`fp16_to_q88` / `q88_to_fp16`），全部过了 iverilog 仿真 + TD 综合，但**未接 PCIe 物理层（SERDES + SGDMA + endpoint core）**。

## Q2 —（无，跳过）

## Q3 — 先用厂商例程 bitstream 打通链路？

**同意，这是正确顺序。** 厂商例程 `AFC03_IMX415_PCIE_X1`（PH1A90SEG324 + PCIe Gen2 x1 / SGDMA H2C/C2H 各一通道）就是现成起点：先「枚举 → 驱动 → 已知 pattern 往返」打通，不被 attention endpoint 阻塞。这本来也是团队 D1–D7 计划。

## Q4 — H2C/C2H 走 SGDMA 哪个 user 设备？

**跟随官方例程**：H2C/C2H 各一通道的 user 设备，`TLAST/TKEEP`、背压、完成通知都与官方例程一致，不另造。具体设备名/时序在枚举打通后与你对齐填 binding。

## Q5 — status 字落在哪个寄存器/节点？

**待 endpoint 寄存器 map 出来后定。** 计划：放 endpoint 的 user 控制寄存器空间，4B pread 读；具体偏移/节点等 endpoint + SGDMA 例程接好后填。

## 关键依赖（不是纯逻辑，需 FPGA 老师）

FPGA 侧 PCIe endpoint 需要：**Anlogic PCIe IP（IPUG011）+ SERDES + SGDMA 控制器**，这是硬件集成（IP 例化 + P&R + 时序收敛 + bitstream），由 FPGA 老师指导。我会把纯逻辑层的接口（AXI-ST 握手 + status 字）先备好，endpoint IP 就位后对接。

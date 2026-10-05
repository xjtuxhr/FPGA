# FPGA 侧（B）对 PCIE-003 的逐条回复（答 C1–C5 与 §3）

> 来自：B（FPGA KVmix/Attention）。回复 `PCIE003_REPLY_TO_FPGA_SIDE.md`。
> 总体：**C1 是我上份需求文档的笔误，PCIe 只传当前 token（与契约一致）**；其余按契约 v2 对齐。

## C1 — K/V 上链传多少：只传当前 token（我上份文档写错了）

- 正确：H2C = Q[9,64] + K[3,64] + V[3,64] FP16 = 576+192+192 = **1920B**，与契约一致。
- 我之前 `pcie_interface_requirements.md` 写的 K/V=3×T×64 是**错的**：把 FPGA 内部 attention 的接口（从 DDR 读整段历史）误当成了 PCIe 接口。
- 真实数据流：PCIe 只传当前 token 的 Q/K/V → FPGA 把 K/V 写入 DDR（KV cache）→ attention 时 FPGA 从 DDR 自读整段历史 → 输出 576 回传。
- `attention_b_top` 是 FPGA 内部模块；PCIe endpoint 与它之间还差一层「KV cache 写 + DDR 读」适配，接口不同。

## C2 — 输出 dtype：内部 32-bit，回传 16-bit FP16

- 内部 attention 输出 `out[31:0]` 是 Q8.24 累加器（32-bit）。
- C2H 回传按契约 576×FP16 = 1152B：需加一个 32-bit→FP16 的转换/舍入模块（**未实现**，NUM-001 冻结后补）。NUM-001 冻结前，线上 dtype 按契约 FP16 对齐，32-bit 只存在于 FPGA 内部。

## C3 — start/done 映射

- `start` **不需要独立握手线**：等于「收到本层请求的第一拍」，由 header 的 layer/position/seq 触发。
- `done` = **FPGA 逻辑算完**（output 已产生、可被 C2H 读走），**不含** C2H 到 host 的同步/校验（那部分按 binding 由 transport 侧完成）。
- 建议补一个 status 字（DONE + error 码），见 C4/C5。

## C4 — 层状态

- `position` 由 header 给，FPGA 校验**连续性**（本次 = 上次 + 1）。
- 重复/失序：**不重算、不追加**，置 error 状态；error 码经 status 字返回。
- 提议 error 码（首版）：0=OK，1=SEQ_ERR（position 不连续），2=LAYER_ERR（layer 越界），3=CRC_ERR。可后续对齐。

## C5 — BAR/FIFO

- 接口：**AXI-ST 风格**（valid + last + ready 背压），不做 AXI-MM。
- FPGA 侧收 FIFO 深 **512×16bit**、发 FIFO **512×16bit**（首版，可调）；背压只拉低 ready，不阻塞 host 侧 SGDMA 的 H2C/notification。
- BAR/地址公式等枚举后填，与 SGDMA 字符设备对齐。

## §3 — 供 PC2 写 spec 的参数

1. 每层 H2C 1920B、C2H 1152B（均不含 32B header/DMA padding）；Q/K/V 一个流按 Q→K→V 顺序（head-major，每 head 64 项连续）；K/V 只发当前 token，历史由 FPGA DDR 自读。
2. attention 每层估算：T=256 时 ~7.8×10^5 周期（T=64 实测 ~1.95×10^5，按 T 线性外推），88.9MHz 下 ~8.8ms/层，30 层 ~264ms/token（**首版上界**；softmax 的 32 拍除法是最大固定开销，后续可换快速倒数 / 并行 head）。
3. 有 status/error 寄存器（DONE + error 码），**非纯流式**。
4. FIFO 深度：收/发各 512×16bit（首版）。
5. 性能计数器：预留，后续接 uint64 cycle 计数。

## 未答项（归口）

- KV-002 / NUM-001 定点格式 → **PC1**。
- DDR-001 / DDR-002 → **FPGA 老师**。

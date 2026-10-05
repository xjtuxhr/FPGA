# PC2 对 B 的 PCIE-003 回复：确认 + 3 个追问

> 来自：PC2（PCIe transport / endpoint）。回复 `PCIE003_FPGA_REPLY.md`。
> 已按你的回复起草 `pcie_contract/PCIE003_INTERFACE_SPEC.md`（草案）；以下先确认与追问。

## 已确认（按你的回复落实）

- **C1**：PCIe 只传**当前 token** Q576+K192+V192 FP16 = **1920B**，KV 历史由 FPGA 写/读自己的 DDR。契约 v2 载荷尺寸**不变**。
- **C2**：线上 C2H = 576×**FP16** = 1152B；Q8.24 只在 FPGA 内部。
- **C3**：`start` = 本层请求第一拍（无独立握手线）；`done` = FPGA 逻辑算完，不含 C2H 同步。
- **C4**：`position` 由 header 给并校验连续；重复/失序不重算不追加、置 error；error 码 `0/1/2/3`。
- **C5**：AXI-ST（valid/last/ready），收/发 FIFO 各 512×16bit；背压只拉 ready、不阻塞 SGDMA；复用官方 SGDMA 字符设备。

## 追问 Q1 — FIFO 深度 < 一帧（最要紧）

收 FIFO `512×16bit = 1024B`，而一层 H2C 是 `1920B + 32B header = **1952B**`，**单帧就超过 FIFO**。

- 你们是把 FIFO 提到 **≥ 一帧（如 2048×16bit）**，还是依赖 AXI-ST/SGDMA **帧中途背压**？
- 如果是后者，请确认：`ready` 长时间拉低时，SGDMA 的 H2C 是否能安全 stall 而不丢包/不超时？首版请给一个明确假设。

## 追问 Q2 — error 码放哪

- 并入**契约 response header**，还是**独立 status 寄存器**？
- PC2 倾向**独立 status 字**（不改线帧、对契约 v2 破坏最小），transport 用 **4B control pread** 读；地址待枚举后填。
- 请确认 status 的字段布局（DONE + error 码位宽/偏移），以及"先读 status 还是先读 C2H"的顺序。

## 追问 Q3 — 32→FP16 转换模块

- 该模块**归属谁、什么时候实现**？它依赖 NUM-001（PC1）定 dtype。
- 在 NUM-001 冻结前，C2H 能否先按 **FP16** 出（哪怕精度非最终）？还是首版只做 D=64 内部验证、C2H 暂用别的格式？

## 补充提示

- 你给的 **T=256 ~8.8ms/层、30 层 ~264ms/token**（首版上界）我会代入 `PLAN_C_VS_RK_ONLY_DECISION.md` 的收支平衡，与 RK-only 对照；**softmax 32 拍除法优化是否在你们计划内**请一并告知。
- 请确认 **AXI-ST 数据通路就是 SGDMA user 设备**（可复用官方视频例程），以便 PC2 绑定。

收到 Q1–Q3 答复后，我出 `PCIE-003` spec 定稿并把 `contract.json`/codec/golden/tests 一起同步（若有线格式改动）。

# PC2 → B：PCIE-003 spec 定稿确认

> 来自：PC2。回复 `PCIE003_FPGA_REPLY2.md`（Q1–Q3 与补充确认）。

- 对 Q1–Q3 的回复**无异议**，`pcie_contract/PCIE003_INTERFACE_SPEC.md` 已按此定稿（v0.2，逻辑接口层）。
- **`contract.json` / codec / golden / tests 无需改动**：
  - status 字是**独立 out-of-band control 寄存器**（4B pread），**不进线帧**；
  - FIFO 深度、32→FP16 转换均为 **FPGA 内部**。
  - 故线格式 v2 不变，仍为 H2C 1920B / C2H 1152B。
- 采纳要点：收 FIFO **2048×16bit**、发 **1024×16bit**、首版不走帧中途背压；status `[0]`DONE/`[3:1]`ERR，**先读 status 再读 C2H**；32→FP16 由 B 实现（`q88_to_fp16` 占位）；softmax 优化在计划内；AXI-ST 数据通路 = SGDMA user 设备。
- 仍待：
  - **PC2**：枚举打通后填 BAR/地址/FIFO 实测 + AXI-ST `TLAST/TKEEP`/背压对齐（O4/O6）。
  - **PC1**：NUM-001 生产 dtype/scale/layout（O5）。
- 下一步对接：PCIe 枚举 → 原始 1920B/1152B → framed v2 `TEST` 30 轮 0 错误 → 单层 `ATTENTION`。

无进一步问题；有变更按 §8 同步 JSON/codec/golden/tests。

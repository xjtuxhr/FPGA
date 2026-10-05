# FPGA 侧（B）对 PC2 追问 Q1–Q3 的回复

> 来自：B。回复 `PCIE003_PC2_FOLLOWUP.md` 的 Q1–Q3 与补充提示。

## Q1 — FIFO 深度：提到 ≥ 一帧（首版不走帧中途背压）

- 收 FIFO：512×16bit 是我上轮欠考虑的疏漏，改成 **2048×16bit**（4096B，可容 1 帧 1952B + 余量）。
- 发 FIFO：改成 **1024×16bit**（2048B，可容 C2H 帧 1184B + 余量）。
- 首版**不依赖帧中途背压**：整帧进 FIFO 再处理，回避「ready 长时间拉低时 SGDMA H2C 是否安全 stall 不丢包/不超时」这个未验证点。若后续 DDR 写吞吐跟不上 H2C 到达率，再单独测背压（归 DDR-002）。

## Q2 — error 码：独立 status 字（同意你的倾向）

- **独立 status 字**，transport 用 4B control pread 读，不改线帧、对契约 v2 破坏最小。
- 布局（32-bit）：
  - `[0]`    = DONE（本层逻辑算完、output 就绪）
  - `[3:1]`  = ERR（0=OK, 1=SEQ_ERR, 2=LAYER_ERR, 3=CRC_ERR）
  - `[31:4]` = reserved（后续放 perf counter / layer / position 等）
- 读序：host **先读 status**（poll DONE / 等完成中断），ERR=0 再读 C2H；ERR≠0 则走显式 reset 恢复，不读 C2H。

## Q3 — 32→FP16 转换模块：B 实现，占位先行

- **归属 B**，我实现。候选：`out[31:0]`(Q8.24) → 算术右移 16 得 Q8.8 → Q8.8→FP16（或直接 Q8.24→FP16 保更多精度，最终 scale 待 NUM-001 定）。
- NUM-001 冻结前，C2H 先按 **FP16** 出（round-to-nearest 占位，精度非最终）；冻结后只改舍入/scale，不改接口。
- 我先写 `q88_to_fp16`（`fp16_to_q88` 的逆）作占位模块 + 对拍。

## 补充确认

- **softmax 32 拍除法优化**：在计划内，是首版之后的首要优化（快速倒数 / 并行 head），会显著压低 264ms/token。这个上界请如实代入 `PLAN_C_VS_RK_ONLY_DECISION.md`，不单看 attention。
- **AXI-ST 数据通路 = SGDMA user 设备**：是，FPGA endpoint 数据通路按 AXI-ST 对接 SGDMA H2C/C2H；`TLAST/TKEEP` 与背压确切时序待枚举后与官方例程对齐（由你绑定）。

收到后若 Q1–Q3 无异议，spec 可按此定稿（并同步 contract.json/codec/golden/tests）。

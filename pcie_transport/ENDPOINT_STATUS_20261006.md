# Endpoint / transport 现状（PC2 → PC1），2026-10-06

目的：给 PC1 一个**不依赖猜测地址**的联调入口，并明确回答 endpoint（FPGA）当前支持情况。
权威证据：`docs/PC2_PCIE1_BRINGUP_REPORT_20261006.md`、`docs/PC2_TO_B_SGDMA_AXIST_INTERFACE.md`。
（本文件只陈述**实测 FACT**；未测到的一律标 ⬜/UNKNOWN，不做推断。）

---

## A. 联调入口（实测，非猜测）

| 项 | 值（2026-10-06 实板） |
|---|---|
| 板卡 | RK3576 EVB1 V10，Debian 12，kernel `6.1.99 #3`，host `linaro-alip` |
| BDF | `0000:21:00.0`（桥 `20:00.0`） |
| vendor:device | `1edb:abcd` |
| 绑定驱动 | `Anlogic-pcie`（module `anlogic_pci`，version 2020.8.21） |
| 设备节点 | `/dev/ANLOGIC-PCI0_user`、`_control`、`_h2c_0`、`_c2h_0`（`root:kvdev 0660`） |
| BAR | BAR0(user) 1M @ PA `0x21200000`；BAR1(config) 64K @ PA `0x21300000`；driver 记录 config bar=1、user bar=0 |
| 寄存器读 | `/dev/ANLOGIC-PCI0_control` + ioctl `ANLOGIC_IOCR`（`_IOR('x',5,struct anlogic_ioc_bar)`=`0x80107805`），`bar_id`+`bar_offaddr`；FPGA app 寄存器在 **BAR0**（`0x5C`=VERSION 等） |
| user 节点偏移 | `SGDMA_USER_BAR_BASE_OFFSET=0x80000`（与控制/raw BAR offset 语义不同，勿混） |
| AXI-ST 接口 | PH1A：`tdata[127:0] / tkeep[15:0] / tuser[15:0] / tlast / tvalid / tready`，H2C×1 + C2H×1（见 docs/PC2_TO_B_SGDMA_AXIST_INTERFACE.md） |
| 工具（RAW） | `pcie_transport/tools/pcie_roundtrip.py`（H2C/C2H 往返）、`tools/smoke_regs.py`（寄存器读） |
| 工具（v2 framed） | `pcie_transport/tools/run_op_test_on_board.py`（需完整 real binding，当前 fail-closed） |

**实测已通过**：
- 枚举：`lspci` → `21:00.0 [1edb:abcd]`，`Mem+ BusMaster+`。
- 寄存器读：`0x5C=0x56440013`（=FPGA `PHASE9_VERSION`）、`0x74` bit0 `link_up=1`。
- **RAW H2C 写**：1920B ×200 全成功，延迟 P50 30.2µs / P99 104.8µs。

---

## B. endpoint 支持情况（明确回答 PC1 的三个问题）

| 问题 | 答案 |
|---|---|
| **C2H 回环 bit 是否已上板？** | **否。** 板上当前是厂商摄像头例程 `imx415_pcie_4k.bit`（sha256 `CB7819…6CDF`）。B 的回环逻辑 `usr_loopback.v` 已写、仿真通过，但**尚未综合/上板**（需厂商 PCIe IP 工程 + 老师）。 |
| **是否支持 v2 的 RESET/OP_TEST/ATTENTION？** | **否。** 当前 bit 未实现 v2（KVMX header / opcode `RESET_CACHE=1`,`TEST=2`,`ATTENTION=0`）。它只有原始 DMA 通路，没有帧头/CRC/opcode 解析。 |
| 当前 endpoint 能力 | 只有 **RAW DMA**：H2C 写能完成（数据被 FPGA 侧 ST 接收）；C2H 读无匹配流（相机帧，无 EOP），读会 10s 轮询超时。 |

**结论**：`run_op_test_on_board.py`（framed v2 / OP_TEST / ATTENTION）**现在无法跑通**——不是 binding 的问题，而是 **endpoint 尚未支持**。RAW 层可先联调 H2C。

---

## C. 依赖 B 的下一步

1. B 出**回环 bit**（H2C→C2H）→ PC2 用 `pcie_roundtrip.py --mode roundtrip --verify` 跑通 RAW 双向。
2. B 出 **v2 endpoint**（KVMX header + opcode + 32B reset ack）→ 再跑 framed v2 `OP_TEST` 30 轮 → 单层 `ATTENTION`。

---

## D. 给 PC1 的接入建议

- 联调请以**设备节点名**为准（`ANLOGIC-PCI0_*`），**不要**用 `/dev/sgdma0_*`（本板不存在）。
- 控制寄存器优先走 `_control` 的 ioctl（`ANLOGIC_IOCR`），不要用 `devmem` 猜物理地址。
- raw 1920B/1152B 与 framed 1952B/1184B 必须**分开标记**（沿用 `pcie_contract/README.md`）。
- 当前可先做：H2C 写入 + 寄存器读；C2H/OP_TEST/ATTENTION 等 B 的 bit。

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
| 工具（RAW） | `tools/pcie_loopback.py`（**H2C→C2H 回环**，并发读）、`tools/pcie_roundtrip.py`（H2C/C2H）、`tools/probe_c2h.py`、`tools/smoke_regs.py` |
| 工具（v2 framed） | `pcie_transport/tools/run_op_test_on_board.py`（需完整 real binding，当前 fail-closed） |

**实测已通过**：
- 枚举：`lspci` → `21:00.0 [1edb:abcd]`，`Mem+ BusMaster+`。
- 寄存器读：`0x5C=0x56440013`（=FPGA `PHASE9_VERSION`）、`0x74` bit0 `link_up=1`。
- **RAW H2C 写**：1920B ×200 全成功，延迟 P50 30.2µs / P99 104.8µs。
- **RAW H2C→C2H 回环**（同日 B 二次烧写后）：`pcie_loopback.py --size 1920 --rounds 100` → **OK=100/100，bad=0 err=0 timeout=0**；往返 `P50=118.0µs P90=136.1µs P99=184.6µs min=31.8µs mean=121.5µs`。
  - **注意**：回环 FIFO 需**边写边读**——必须常驻读 C2H 排空，否则 H2C 写会阻塞/偶发 `errno 512`；`pcie_loopback.py` 用后台读线程处理。

---

## B. endpoint 支持情况（明确回答 PC1 的三个问题）

| 问题 | 答案 |
|---|---|
| **C2H 回环 bit 是否已上板？** | **已上板且回环确认生效**（2026-10-06，B 第二次烧写后）。写 1920B H2C → C2H 原样读回，`pcie_loopback.py` OK=100/100、P50 118µs。需**并发读写**（见 A 节注意）。 |
| **是否支持 v2 的 RESET/OP_TEST/ATTENTION？** | **否（仍未支持）。** 当前是**原始回环** bit，未实现 v2（KVMX header / opcode `RESET_CACHE=1`,`TEST=2`,`ATTENTION=0`）。 |
| 当前 endpoint 能力 | **RAW 双向**：H2C 写 ✅、C2H 回环 ✅（并发读写）；寄存器读 ✅。v2 framed / OP_TEST / ATTENTION ⬜。 |

**结论**：RAW 双向（1920B 回环）**已打通**；`run_op_test_on_board.py`（framed v2 / OP_TEST / ATTENTION）**仍跑不了**——endpoint 尚未实现 v2 帧。以 `pcie_contract/README.md` 的 raw / framed 分开标记。

---

## C. 依赖 B 的下一步

1. ~~回环 bit（H2C→C2H）~~ ✅ **已上板并确认**（`pcie_loopback.py` OK=100/100，P50 118µs）。
2. B 出 **v2 endpoint**（KVMX header + opcode + 32B reset ack）→ 再跑 framed v2 `OP_TEST` 30 轮 → 单层 `ATTENTION`。

---

## D. 给 PC1 的接入建议

- 联调请以**设备节点名**为准（`ANLOGIC-PCI0_*`），**不要**用 `/dev/sgdma0_*`（本板不存在）。
- 控制寄存器优先走 `_control` 的 ioctl（`ANLOGIC_IOCR`），不要用 `devmem` 猜物理地址。
- raw 1920B/1152B 与 framed 1952B/1184B 必须**分开标记**（沿用 `pcie_contract/README.md`）。
- 当前可做：H2C 写 + **C2H 回环（并发读写）** + 寄存器读；v2 framed/OP_TEST/ATTENTION 等 B 的 v2 bit。

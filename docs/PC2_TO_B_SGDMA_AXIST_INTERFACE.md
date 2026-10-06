# PC2 → B：SGDMA 设备节点名 + H2C/C2H AXI-ST 接口说明

来源：PC2（在 RK3576 实板 + 厂商 `AFC03_IMX415_PCIE_X1` 工程核对）。日期：2026-10-06。
用途：供 B 设计 attention endpoint 侧的 AXI-ST 对接。**带 file:line 的可回查；标 FACT 的是源码/实板事实，标 TODO 的是需 IP 手册确认的。**

---

## 1. 实际设备节点名（FACT，实板 + 源码）

运行板：RK3576，驱动 `anlogic_pci`（version 2020.8.21），`poll_mode=1`。

命名来自 `deploy/sgdma_drv/anlogic_pci_cdev.h:28`：`#define ANLOGIC_NODE_NAME "ANLOGIC-PCI"`，
配合格式串（`anlogic_pci_cdev.c:40-48`）：`"%d_user" "%d_control" "%d_xvc" "%d_events_%d" "%d_h2c_%d" "%d_c2h_%d" "%d_bypass_h2c_%d" "%d_bypass_c2h_%d" "%d_bypass"`。
第一个 `%d`=器件序号(0)，第二个 `%d`=通道号(0)。

**板上实测存在的节点：**

| 节点 | 用途 |
|---|---|
| `/dev/ANLOGIC-PCI0_user` | user BAR0 窗口（偏移 `+0x80000`，见下） |
| `/dev/ANLOGIC-PCI0_control` | ioctl 控制（配置/寄存器/复位等） |
| `/dev/ANLOGIC-PCI0_h2c_0` | H2C 通道 0（host→card） |
| `/dev/ANLOGIC-PCI0_c2h_0` | C2H 通道 0（card→host） |

> ⚠️ **没有 `/dev/sgdma0_*`**。厂商 `pcie_speedtest_gui.py`/`diag_dma_test.sh` 里的 `/dev/sgdma0_*` 在本板**不存在**，任何脚本要改用 `ANLOGIC-PCI0_*`。
> 可能的其它节点（`xvc`、`events_%d`、`bypass*`）本板未创建。
> `SGDMA_USER_BAR_BASE_OFFSET = 0x80000`（`anlogic_pci_lib.h:83`）：user 字符设备的 read/write 相对 BAR0 有 +0x80000 偏移，**不等于** `devmem BAR0+off`。

---

## 2. H2C / C2H 的 AXI-ST 接口（FACT）

顶层参数（`uisrc/01_rtl/imx415_pcie_top.v:15-20`）：`DEVICE_FAMILY="PH1A"`, `DATA_WIDTH=128`, `KEEP_WIDTH=16`, `H2C_CHNL_NUM=1`, `C2H_CHNL_NUM=1`, 且 `AXI4ST_BUS_EN=1`。
（PH1A 对应 128-bit；见 `sgdma_subsys.v:21-24`。）

在用户逻辑边界（`sgdma_subsys.v:78-92` / `sgdma_app.v:69-83`）信号如下。**B 的 endpoint 与这批信号直接对接：**

### H2C = SGDMA 核心 → 用户逻辑（卡内收数据）
| 信号 | 方向(相对用户) | 宽度 | 含义 |
|---|---|---|---|
| `m0_axis_h2c_tdata` | 输入 | 128 | 数据 |
| `m0_axis_h2c_tkeep` | 输入 | 16 | 每字节有效 |
| `m0_axis_h2c_tuser` | 输入 | 16 | sideband（demo 原样透传，位定义 TODO） |
| `m0_axis_h2c_tlast` | 输入 | 1 | 包末拍（=descriptor EOP） |
| `m0_axis_h2c_tvalid` | 输入 | 1 | 核心有效 |
| `m0_axis_h2c_tready` | **输出** | 1 | **用户给核心的背压** |

### C2H = 用户逻辑 → SGDMA 核心（卡内发数据）
| 信号 | 方向(相对用户) | 宽度 | 含义 |
|---|---|---|---|
| `s0_axis_c2h_tdata` | 输出 | 128 | 数据 |
| `s0_axis_c2h_tkeep` | 输出 | 16 | 每字节有效 |
| `s0_axis_c2h_tuser` | 输出 | 16 | sideband |
| `s0_axis_c2h_tlast` | 输出 | 1 | 包末拍（=EOP） |
| `s0_axis_c2h_tvalid` | 输出 | 1 | 用户数据有效 |
| `s0_axis_c2h_tready` | **输入** | 1 | **核心给用户的背压** |

核心内部叫法：H2C = `m_axis_rx_*`，C2H = `s_axis_tx_*`（`sgdma_subsys.v:900-912`）。

厂商 demo 的用法参考：`sgdma_app/src/usr_axi4st_h2c.v`（H2C 侧，`tready` 由 `fifo_rdy` 产生）、`usr_axi4st_c2h.v`（C2H 侧）。顶层还用了 `axis_stream_fifo` 吸收 SGDMA 的 `tready` 间隙（`imx415_pcie_top.v:611`）。

---

## 3. TLAST / TKEEP 语义

- **握手**：标准 AXI-ST。上升沿 `tvalid & tready` 同时为高时传送一拍。`tvalid` 拉高后数据/keep/last 必须保持到 `tready`。
- **TLAST**：`tlast=1` 的那一拍是**包末拍**，与描述符控制位 `SGDMA_DESC_EOP (1<<4)`（`anlogic_pci_lib.h:197`）对应。
  - H2C：核心按 host 侧的 EOP 在末拍置 `tlast`。
  - C2H：**用户逻辑必须在包的最后一拍置 `tlast`**，否则 host 侧收不到 EOP。
- **TKEEP**：每 bit 对应 tdata 的一个字节（128-bit→16 bit）。1=该字节有效。demo 里 `tkeep==0` 的字节被强制清零（`usr_axi4st_h2c.v:68`）。末拍常用 keep 表示不足 128-bit 的尾字节。**非末拍是否恒为全 1、末拍如何对齐，属 TODO（需 IP 手册确认）。**
- **TUSER**：16-bit，demo 只做透传（H2C 存入 FIFO、C2H 取回）。**位定义/用途 TODO。**

发包长度与拍数：H2C 1920B=120 拍，C2H 1152B=72 拍（128-bit/16B 每拍）。

---

## 4. 背压（FACT + TODO）

- **H2C**：背压完全由用户 `m0_axis_h2c_tready` 决定；用户不 ready 时核心保持 `tvalid`+数据。
- **C2H**：背压由核心 `s0_axis_c2h_tready` 给出；用户必须保持数据直到 `tready`。
- **C2H 信用（credit）流控**（可选，本板已开 `enable_st_c2h_credit=1`）：
  - 公共寄存器 `struct sgdma_common_regs { ... u32 credit_mode_enable; ..._w1s; ..._w1c; }`（`anlogic_pci_lib.h:399-404`）。
  - 引擎寄存器 `struct engine_sgdma_regs { ... u32 credits; }`（`:356-366`），`credits` 位见 `anlogic_ring.c:181-183,679-680`。
  - 含义：host/C2H-ST 可预填的缓冲/描述符数量由 credit 控制，用完即背压。**credit 的粒度（字节/拍/页/描述符）TODO。**
  - 引擎控制位：`SGDMA_CTRL_STM_MODE_WB (1<<27)`、`SGDMA_CTRL_POLL_MODE_WB (1<<26)`（`:131-132`）。

首版建议（与既有结论一致）：**帧中途不做背压**，整包（1920B/1152B）一次收发，靠 credit 控制包级节奏。

---

## 5. 完成通知（FACT）

有两条路，**本板用的是轮询**（`insmod ... poll_mode=1`，日志 `poll mode active, skip MSI/MSI-X and IRQ setup`）：

- **轮询完成（本板）**：`engine_regs` 的 `status`（`BUSY(0)/DESC_STOPPED(1)/DESC_COMPLETED(2)`…，`:134-141`）与 `completed_desc_count`；或 poll writeback `poll_mode_wb_lo/hi`（`:340-341`，`struct sgdma_poll_wb`）。
- **中断完成（可选，MSI_EN=1）**：`struct interrupt_regs`（channel/user_int_enable/request/pending + MSI 向量，`:379-397`）；RTL 侧 `usr_irq`（`usr_irq_req/ack`，`sgdma_app.v:767-779`）。
- **描述符级**：`struct sgdma_desc.control` 的 `SGDMA_DESC_STOPPED(0)/SGDMA_DESC_COMPLETED(1)/SGDMA_DESC_EOP(4)`（`:194-197`）。
- **C2H 结果**：`struct sgdma_result { u32 status; u32 length; ... }`（`:438-442`），`status` 的 bit0 = `RX_STATUS_EOP`（`:108`，收到 EOP）。

---

## 6. 描述符与关键寄存器（FACT）

`struct sgdma_desc`（`anlogic_pci_lib.h:421-435`）：
```
u32 control; u32 bytes;
u32 src_addr_lo, src_addr_hi;
u32 dst_addr_lo, dst_addr_hi;
u32 next_lo, next_hi;
```
`SGDMA_DESC_BLEN_MAX = 1<<27`（单描述符最大 128 MiB）。

`struct engine_regs`：`control/control_w1s/control_w1c`、`status/status_rc/completed_desc_count`、`poll_mode_wb_lo/hi`、`interrupt_enable_mask*`、`perf_*`。
`struct engine_sgdma_regs`：`first_desc_lo/hi`、`first_desc_adjacent`、`credits`。

**描述符旁路接口**（用户逻辑自己产描述符，`sgdma_subsys.v:136-200`）：
`c2h_dsc_byp_ready/load/src_addr[63:0]/dst_addr[63:0]/len[27:0]/ctl[15:0]`，h2c 同构。`ctl` 含 EOP 等控制位（**位定义 TODO**）。B 若要由 FPGA 主动发 C2H，可走这条。

---

## 7. 可回查的源文件

- `uisrc/01_rtl/imx415_pcie_top.v:15-20,86-106,277-323`（参数 + ST 连接）
- `uisrc/03_ip/sgdma/sgdma_subsys.v:78-92,800-920`（ST 端口与核心映射）
- `uisrc/03_ip/sgdma/sgdma_app/src/sgdma_app.v:69-83`（ST 端口）
- `uisrc/03_ip/sgdma/sgdma_app/src/usr_axi4st_h2c.v` / `usr_axi4st_c2h.v`（厂商用法）
- `deploy/sgdma_drv/anlogic_pci_lib.h`（描述符/寄存器/状态位）
- `deploy/sgdma_drv/anlogic_pci_cdev.h:28` + `anlogic_pci_cdev.c:40-48`（节点名）
- 加密核心：`uisrc/03_ip/sgdma/src_enc/sgdma_ip_all.enc.v`（**不可读**，内部时序需 IP 手册）

---

## 8. 需 B 用厂商 SGDMA IP 手册确认（TODO）

1. `tkeep` 在非末拍/末拍的精确规则；`tlast` 与 `tready` 的相位关系。
2. `tuser[15:0]` 的位定义与用途。
3. credit 的粒度与释放时机（字节/拍/页/描述符）。
4. 单包最大拍数、以及跨描述符边界的 `tlast` 行为。
5. 完成/中断延迟（用于 30 层依赖链计时）。

---

## 9. 已确认（2026-10-06，回应 B）

**Q: tkeep 能假设全程全 1 吗？** —— 可以。
- 厂商自己的 C2H 就是全程全 1：`imx415_pcie_top.v:665` `assign s0_axis_c2h_tkeep = {KEEP_WIDTH{1'b1}}`；`usr_axi4st_c2h.v:50` 默认也是全 1。
- 本项目合同：H2C 1920B = 120×16B、C2H 1152B = 72×16B，**都是 128-bit/16B 的整数倍、无残缺尾拍**，故全 1 正确。
- 例外（TODO）：若将来发**非 16B 整倍数**的包，末拍必须用 `tkeep` 掩掉无效字节，否则 host 会多写/多读。

**Q: tuser 置 0 还是透传？** —— 置 0 可接受。
- 驱动/host **不解释** FPGA 内部 ST 的 `tuser`；EOP 依靠 `tlast`（H2C/C2H）+ 描述符 `SGDMA_DESC_EOP (1<<4)`。厂商 demo 里 `tuser` 仅透传。
- 厂商板 C2H 写的是 `{KEEP_WIDTH{1'b1}}`（`imx415_pcie_top.v:666`），但那是选择、非强制。为与厂商已知配置一致可写全 1；写 0 不影响正确性。

**Q: 当前 bit 有没有 H2C→C2H 回环？**
- `imx415_pcie_top.v`：H2C 接到 `u_sgdma_app`（厂商 ST app，内部含 loopback FIFO `usr_axi4st_lp`）；C2H 由视频帧驱动（`:664-668`）。是否真回环取决于该 app 的 `usr_lp0rw_run`（由 AXI-L 的 start/mode 控制）——**以 B 的工程以准**。
- 回环**仅用于链路自测**；正式目标仍是 B 的 attention 通路（H2C 1920B 进 → C2H 1152B 出）。B 已备 `usr_loopback.v`（仿真通过），待厂商 PCIe IP 工程重新综合出 bit。


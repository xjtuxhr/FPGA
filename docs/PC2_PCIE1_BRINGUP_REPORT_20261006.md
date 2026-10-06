# 阶段汇报：RK3576 PCIe1（PCIe1 ↔ Anlogic FPGA）打通

- 日期：2026-10-06
- 汇报人：PC2
- 板卡：MLK-AFH03-AFC03，RK3576 EVB1 V10 + PH1A90SEG324
- 关联：PCIE-001 / PCIE-005、`PCIE_BRINGUP_RUNBOOK.md`、`VENDOR_PCIE_REFERENCE.md`

---

## 一、结论摘要

RK3576 侧 PCIe1 已从**完全不通**推进到**链路通 + 驱动/寄存器读写通 + H2C 数据通路实测通过**，且**全部开机自动、可复现**。

- 链路：`PCIe Gen.2 x1 link up`，FPGA endpoint `1edb:abcd` 在 `0000:21:00.0` 枚举。
- 驱动：`anlogic_pci` 绑定，节点 `/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}`（`root:kvdev 0660`）。
- 数据通路：从 RK 用户态读到 FPGA 寄存器（`VERSION=0x56440013`）；H2C 1920B 写 200/200 成功，延迟 P50 30.2µs / P99 104.8µs。
- 仅剩：**C2H / 完整往返需 B 的 FPGA endpoint 或回环 bit**（等综合）。

---

## 二、关键成果与证据

| 项 | 结果 | 证据 |
|---|---|---|
| 运行 DT `pcie@2a210000` | `disabled` → `okay` | `/proc/device-tree/pcie@2a210000/status` |
| 链路 | Gen2 x1 link up | `dmesg`: `rk-pcie 2a210000.pcie: PCIe Gen.2 x1 link up` |
| 端点 | `21:00.0 [1edb:abcd]`；桥 `20:00.0 [1d87:3576]` | `lspci -nn` |
| BAR | BAR0 1M@`0x21200000`，BAR1 64K@`0x21300000` | `lspci` / sysfs resource |
| 驱动绑定 | `Anlogic-pcie`，`Mem+ BusMaster+` | `lspci -vv -s 21:00.0` |
| 寄存器读 | `0x5C=0x56440013`(=FPGA `PHASE9_VERSION`)、`0x74=0x00000c01`(link_up=1) | ioctl `ANLOGIC_IOCR` 读 BAR0 |
| H2C 数据通路 | 1920B ×200 全成功 | `/home/kvdev/pcie_roundtrip.py --mode h2c` |
| 开机自动 | pcie1-fpga + anlogic-sgdma 两服务 | 重启实测（无需手动） |

---

## 三、关键根因（为什么之前一直连不上）

1. 运行 DT 里 `pcie@2a200000`、`pcie@2a210000` **都是 `disabled`** → `rk-pcie` 不 probe，`lspci` 空。
2. p3 是 **U-Boot FIT**；真正被内核使用的 DTB 有**两份**：
   - FIT `/images/fdt`；
   - **resource 镜像内嵌的 DTB 副本**（`sgdma_subsys`/U-Boot 实际采用）。
   **只改 `/images/fdt` 无效**——这是本轮最大坑。
3. 两份 DTB **无 signature 节点**（只有 sha256），可安全等长 patch。
4. pcie1 节点缺 `reset-gpios`(gpio-48) 与 `vpcie3v3-supply`(gpio-124 regulator)，status=okay 后仍需手动上电/复位。
5. 旧工具 `patch_pcie1_dtb.py` 把 p3 当裸 DTB，对本板 FIT 无效。

---

## 四、做了哪些改动（可复现）

**4.1 p3（boot 分区）**
- 两份 DTB 的 `pcie@2a210000` `disabled`→`okay`（等长，offset 不变），重算 FIT 的 sha256 hash 节点。
- p3 整盘 sha256：`faebf164…abec` → `a375de3e41df59cd4f79dbd8a9d0918d3c968a14e526fb513d31e5516b17048e`
- `/images/fdt` 区域：`a30ce313…fa3dd` → `839bcc91…0099`
- kernel[292864,40071680] 与未改区域**逐字节不变**。
- 备份：`/userdata/p3_backup_before_pcie_20261006.img`（= 原始）。
- 回滚：`dd if=/userdata/p3_backup_before_pcie_20261006.img of=/dev/mmcblk0p3 bs=1M conv=fsync; sync; reboot`

**4.2 开机服务（持久化）**

| 文件 | SHA256 |
|---|---|
| `/usr/local/sbin/pcie1-fpga.sh` | `604bc1c0c87236c7c455fa5853d177a2c2e5f3970491d371b0b2a42a7f6719dd` |
| `/etc/systemd/system/pcie1-fpga.service` | `f0a9bbc59809c4c43fed07ce1ad750848ace895caa50388fb2e24e0c571c56a7` |
| `/etc/systemd/system/anlogic-sgdma.service` | `c1b7e58a73775af7963308c8333a228a7bde586fe1b2fe1d7d5c4b1ddeede7e6` |
| `/lib/modules/6.1.99/extra/anlogic_pci.ko` | `fb04231eb5671a87f9b71f4b9e429fb7007bdcabcbddfebe11c640c10b21007e` |

逻辑：`pcie1-fpga` 在开机时释放/上电 gpio-124 → PERST#(gpio-48) 脉冲 → `bind rk-pcie`；`anlogic-sgdma` 随后 `insmod anlogic_pci.ko`。均幂等。

**4.3 网络持久化（解决 LNX-002）**
- `nmcli` 配静态连接 `pcie-end0`(192.168.137.101/24)、`pcie-end1`(192.168.138.101/24)，重启不丢。

**4.4 权限**
- PC1 安装 `/etc/udev/rules.d/99-anlogic-pci.rules`，节点 `root:kvdev 0660`，kvdev 可测。

---

## 五、产出物

- 本汇报：`docs/PC2_PCIE1_BRINGUP_REPORT_20261006.md`
- 给 B 的 AXI-ST 接口：`docs/PC2_TO_B_SGDMA_AXIST_INTERFACE.md`（设备名/信号/TLAST/TKEEP/背压/完成通知/寄存器）
- 给 PC1 的操作单：`docs/PC1_SGDMA_PERMISSION_TODO_20261006.md`
- 板上：`/home/kvdev/pcie_roundtrip.py`、`/home/kvdev/smoke_regs.py`、两个 systemd 服务 + `anlogic_pci.ko` + p3 原始备份

---

## 六、与 B 的接口对接结论

- 设备名：`/dev/ANLOGIC-PCI0_*`（**不是** `/dev/sgdma0_*`）。
- H2C/C2H AXI-ST：PH1A → `tdata[127:0] / tkeep[15:0] / tuser[15:0] / tlast / tvalid / tready`，各 1 通道。
  - H2C（核心→用户）：用户给 `tready` 背压；`tlast` = 包末（descriptor EOP）。
  - C2H（用户→核心）：核心给 `tready`；**用户必须在末拍置 `tlast`**。
- 已确认 B 的两个疑问：
  - **tkeep 全程全 1：可以**（合同 1920B=120×16B、1152B=72×16B，均整除 16B；厂商亦如此）。
  - **tuser 置 0：可以**（驱动不解释；只靠 `tlast`/描述符 EOP）。
- 首版建议：帧中途不背压，整包收发。

---

## 七、待办 / 阻塞

| 项 | 负责 | 状态 |
|---|---|---|
| B 回环 bit（`usr_loopback.v` 逻辑就绪，待厂商 IP 工程综合） | B/老师 | ⬜ |
| B attention endpoint（按 AXI-ST 文档） | B | ⬜ |
| C2H 1152B 与完整往返延迟（`pcie_roundtrip.py --mode roundtrip --verify`） | PC2 | ⬜ 等 bit |
| 可选：pcie1 加 `reset-gpios`/`vpcie3v3-supply`（消除开机 regulator WARNING） | PC2 | 可选，非阻塞 |

---

## 八、风险与边界

- 重刷 p3 会覆盖当前配置；已在 `/userdata`、`/home/kvdev` 留原始备份。
- 开机 `pcie1-fpga` 会打印一条 `WARNING ... regulator_unregister`（无害）。
- **不要**盲跑 `pcie_setup.sh` / `pcie1_enable.sh` / `build_drivers.sh` 等（有写盘/重编译/重绑副作用，本板已用另一套方案）。
- 本轮只证明 PCIe1 链路、驱动、寄存器读、H2C 写通路；**未宣称** C2H 或 Attention 通路通过。

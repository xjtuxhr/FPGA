# 首版 PCIe 打通路线（厂商例程）— 给 B / PC1 / FPGA 老师

> 来自：PC2。回应 B 的 `PCIE003_FPGA_REPLY3.md`（"没有 endpoint bit，先用厂商例程"）。
> 结论：**随板厂商例程就是现成起点**，已定位到全部制品。

## 已定位的厂商制品（本地）

路径：`MLK-AFH03-AFC03\板卡资料\03_course\07_异构教程\AFC03_IMX415_PCIE_X1\...\IMX415_PCIE_X1`

- **endpoint bitstream**：`imx415_pcie_4k_Runs\best_result\imx415_pcie_4k.bit`
  - 4850315 B，sha256 `CB78194C3287F538C96391BBE37E6FEC2701BA8C79A7FE6A90305761CAD66CDF`
- **SGDMA 驱动源码**：`deploy\sgdma_drv\*`（H2C/C2H user 设备）
- **使能脚本**：`deploy\pcie1_enable.sh`、`pcie1_rebind.sh`、`pcie_setup.sh`、`pcie1-rebind.service`
- **PCIe IP**：`al_ip\PH1_LOGIC_PCIE*`、`pcie_brg_pcie_core`、`sgdma_pll`
- **教程**：`2026...异构AFC03教程-PCIE篇.pdf`

## 建议顺序（首版链路，先跑通不接 attention）

1. **FPGA**：烧 `imx415_pcie_4k.bit`（TD Programmer / 现场）。
2. **RK**：使能 `pcie@2a210000`（DTB status）+ **PERST#/电源**，重启。
3. **驱动**：编译/加载厂商 SGDMA 驱动 → `/dev/ANLOGIC*`、`/dev/sgdma*`。
4. **验证**：原始 1920B 下发 / 1152B 返回 → framed v2 `TEST` 30 轮 → 填 `TRANSPORT_BINDING`。

## 关键坑（必须知道）

- **只改 DTB status 可能枚举不到**：厂商 `pcie1_enable.sh` 还做：
  - **PERST# = GPIO1_C0 = gpio-48**（拉低再拉高释放 FPGA 复位）；
  - **vcc3v3_pcie 电源 = GPIO3_D4 = gpio-124**（置 1 上电）；
  - 用 systemd 服务 `pcie1-fpga` 开机执行。
- 详细见仓库 `pcie_transport/VENDOR_PCIE_REFERENCE.md` 与 `PCIE_BRINGUP_RUNBOOK.md`。

## 分工 / 需要谁

- **FPGA 老师**：烧 endpoint bit；确认板级 PCIe 供电/复位连接。
- **串口操作者（现场）**：重启、重启后补 `end0` 网络（LNX-002）。
- **PC2**：RK 使能 + 驱动 + binding + 原始/framed 验证（协调窗口内）。
- **B**：后续把 attention endpoint 接到同一 SGDMA（H2C/C2H + status 字）。

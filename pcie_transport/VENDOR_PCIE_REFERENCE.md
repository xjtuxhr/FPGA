# 厂商 PCIe 例程参考（AFC03_IMX415_PCIE_X1）

状态：**参考/只读整理**，未执行。用途：为首版 PCIe 链路 bring-up 提供现成制品（endpoint bit + 驱动 + 使能脚本）。
来源：随板资料 `MLK-AFH03-AFC03\板卡资料\03_course\07_异构教程\AFC03_IMX415_PCIE_X1\AFC03_IMX415_PCIE_X1\IMX415_PCIE_X1`。
不把厂商"一键脚本"当只读诊断；执行属系统变更，须走协调窗口（`COOPERATION.md`）。

## 1. 关键制品

| 制品 | 位置（相对例程根） | 说明 |
|---|---|---|
| **endpoint bitstream** | `imx415_pcie_4k_Runs\best_result\imx415_pcie_4k.bit` | **4850315 B，sha256 `CB78194C3287F538C96391BBE37E6FEC2701BA8C79A7FE6A90305761CAD66CDF`** |
| 压缩 bit | `...\best_result\imx415_pcie_4k_compress.bit` | 3761133 B |
| PCIe IP | `al_ip\PH1_LOGIC_PCIE*`、`al_ip\pcie_brg_pcie_core`、`al_ip\sgdma_pll`、`al_ip\ui_pll` | Anlogic PCIe IP + SGDMA PLL |
| DTB 补丁工具 | `deploy\patch_pcie1_dtb.py` | 只把 `pcie@2a210000` status 改 okay；备份到 `/tmp` |
| 使能脚本 | `deploy\pcie1_enable.sh`、`pcie1_rebind.sh`、`pcie_setup.sh`、`pcie1-rebind.service` | 含 **PERST#/电源 GPIO** 与 systemd 服务 |
| SGDMA 驱动源码 | `deploy\sgdma_drv\*`（`anlogic_pci_drv.c`、`cdev_sgdma.c`、`anlogic_pci_test.c`、`sgdma_case_st.c` …） | 官方 H2C/C2H user 设备来源 |
| v4l2 驱动 | `deploy\v4l2_drv\milianke_v4l2_zerocopy.c` | 视频通路（参考） |
| 教程 PDF | `07_异构教程\AFC03_IMX415_PCIE_X1\...\2026...异构AFC03教程-PCIE篇.pdf` | 步骤说明 |

## 2. 厂商流程（readme.txt 摘要）

1. RK3576 烧 `mlk-rk03-debian.img` 固件，并**升级 `boot.img`（含新 DTS）**（或用新 DTS 构建 `update.img`）。
2. 把 `deploy/` 拷到 RK3576 `/root/deploy/`，`chmod +x *.sh`，执行 `./pcie_setup.sh`（编译驱动、安装、绑定 PCIe 链路）。
3. **前提：FPGA 端已烧好 `imx415_pcie_4k.bit`（或固件启动）。**
4. 用 v4l2 验证（`gst-launch ... v4l2src device=/dev/video73 ...`）。

## 3. 关键坑：只改 DTB status 可能不够

`pcie1_enable.sh` 除补 DTB status 外，还做 **运行期 GPIO 初始化**：

- **PERST# = GPIO1_C0 = gpio-48**：先拉低（assert）→ 拉高（deassert）释放 FPGA 复位；
- **vcc3v3_pcie 电源 = GPIO3_D4 = gpio-124**（与 pcie0 可能共用）：置 1 上电；
- 并通过 systemd 服务 `pcie1-fpga` 每次开机自动执行。

→ 我们的 `patch_pcie1_dtb.py`+重启若仍枚举不到，很可能缺 **PERST#/电源** 这两步；需按厂商脚本处理（属系统变更，需协调）。

## 4. 与我们工具的关系

- 我们的 `pcie_transport/tools/patch_pcie1_dtb.py` 是 vendor `deploy/patch_pcie1_dtb.py` 的**加固版**：真实 FDT 结构遍历（非字符串搜索）、备份到 `/userdata`、与运行内核 DTB 交叉校验、fail-closed。二者都只做 status 补丁。
- vendor 版 sha256 `34D8...`，我们版 `831A...`（不同文件）。
- 设备节点/驱动绑定仍以**实板枚举**为准，不照抄 vendor 命名。

## 5. 建议路线（首版链路）

1. **FPGA**：用 TD Programmer 烧 `imx415_pcie_4k.bit`（需 FPGA 老师/现场）。
2. **RK**：使能 PCIe1（我们的加固补丁或 vendor 流程）+ **PERST#/电源处理** → 重启 → `lspci` 应出现端点（`1edb:...`）。
3. **驱动**：编译/加载 vendor SGDMA 驱动 → `/dev/ANLOGIC*`、`/dev/sgdma*` → 与 `TRANSPORT_BINDING` 对齐。
4. **验证**：原始 1920B/1152B → framed v2 `TEST` 30 轮 → 填 binding。

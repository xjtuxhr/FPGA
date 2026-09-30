# RK3576 Linux、NPU 与异构开发入口

更新：2026-09-30。面向 **MLK-AFH03-AFC03 / RK3576 + PH1A90SEG324、方案 C、SmolLM-135M**。本文是随板教程的项目导航，不替代原教程。成员已实测 Debian 12 串口与 `kvdev` SSH 登录；NPU、PCIe、FPGA推理仍未实测。涉及烧写和模块加载时按原始图示逐步核对。活动问题统一写入 [UNKNOWNS](UNKNOWNS.md)，日常连接先看 [启动清单](../STARTUP_CHECKLIST.md)。

## 1. 来源层级与覆盖

优先级：随板官方板卡/入门资料与适配示例 > 随板课程 > `Wechat_ref` 工程经验 > 通用知识。不同版本不合并成一个“已验证环境”。下列原始资料位于本地 `MLK-AFH03-AFC03/learningresources`，**没有随本次 Git 文档提交上传**；协作者可读本文，复现具体板卡操作前需另行取得原始教程。递归盘点范围：

| 目录（相对 `MLK-AFH03-AFC03/learningresources`） | 文件数 | 阅读重点与边界 |
|---|---:|---|
| `01_start/01_start_linux` | 7 | 6 份 PDF 全文与关键板卡图：出厂 Buildroot、PuTTY/串口、Windows 恢复烧录、交叉开发；`USB_CAN TOOL.rar` 是 CAN 附件，未解包或执行 |
| `03_course` | 1000 | Linux 系统/设备/驱动、RKNN、RKLL、OpenCV、异构 PCIe/MIPI 的教程及相关源码、脚本和工程；`.o/.whl/.img/.bit` 等二进制只登记用途，不称作“逐行阅读” |
| `Wechat_ref` | 2 | 两份 TXT 只作 PRACTICAL REFERENCE，不覆盖板卡教程 |

原始入门 PDF 位于 `01_start/01_start_linux`：`资料介绍.pdf`、`01_prepare/1_部署虚拟机环境.pdf`、`01_prepare/2_PuTTY安装与使用.pdf`、`02_test_board/1_Linux出厂系统测试.pdf`、`03_restore_factory/1_Linux恢复出厂设置.pdf`、`04_secondary_development/1、二次开发buildroot篇.pdf`。教程为 REV2026、2026-03 版。课程根目录含 `01-AFC03教程Linux系统篇` 至 `07_异构方案`；下文索引列出真正可复用的入口。未发现本地 `mlk-sdk-3576-v1.1.0.tar.gz` 或预制 Ubuntu VM；教程提到的外部资源不能当作已在仓库中。

**安全提醒：** 出厂测试 PDF 包含向 U 盘、TF 分区、NVMe 原始设备写零的 `dd` 示例，也建议关闭电脑全部防火墙。这些仅是厂测方法，**不得照抄到项目日常验证**；会毁坏介质数据或削弱 PC 防护。读设备名、`lsblk`/`fdisk -l` 本身不授权写设备。

清单按目录递归取得，正文深入阅读与项目直接有关的 6 份入门 PDF、3 份 Linux DOCX、3 份 NPU/OpenCV PDF、2 份异构 PDF、两份 Wechat TXT、相关构建/驱动/RTL 源码及归档目录。另对 Linux 设备篇 `01_wifi` 的 6 份 PDF 核对页数、检索全文并阅读相关章节；它们不提供本板 SSH/文件传输的证明（见下节），不声称逐页精读全部 132 页。`03_course` 的 1000 个条目包含大量重复产物、`.o/.whl/.img/.bit/.rknn` 二进制、视频/摄像头示例和加密 SGDMA 核；没有声称逐个反汇编或运行。`USB_CAN TOOL.rar` 未解包（CAN 附件非当前路径）；`rk03-driver-demo.tar.gz` 可列出 233 条目，但其中预编译 `.ko` 不等于已审源/可在当前内核使用；`rkll-toolkit2.rar` 与嵌套 ZIP 的关键头/示例已读。加密 `sgdma_ip_all.enc.v` 的内部实现无法直接审阅。没有发现本轮因损坏/加密而无法读取的**相关教程正文**；外部缺失包与版本冲突见下表。

## 2. 当前系统与开发依赖链

```text
Windows PC（VSCode/Git/TD；可选 Ubuntu 22.04 VM 做供应商 SDK 交叉构建）
  → 核对板卡/BOM、现有系统和 UART boot log
  → 只有确需换系统且用户确认时才进入镜像烧录
  → 登录 RK3576 Linux，记录 OS/kernel/内存/网络/设备节点
  → 确认 NPU driver + runtime 版本，运行官方样例
  → PC 侧转换或准备模型制品，RK 侧部署 runtime/二进制/模型
  → PCIe 精确 vendor/device/BDF 枚举与双向 sample 校验
  → NPU MatMul 每个真实 Smol shape 对拍并测 M=1
  → FPGA B Attention/KV 单层联调，再集成 kv_host 与30层调度
  → 固定版本、质量与端到端计时
```

入门总览称**出厂默认 Buildroot**（`资料介绍.pdf` §1.1–1.2）；本项目实板由成员于2026-09-30通过 `/etc/os-release` 确认为 **Debian 12 bookworm**，具体供应商镜像/boot版本仍未知。现有系统已可串口和 SSH 登录，不需为开始开发而重刷。PC 可继续用 Windows；教程所用 Ubuntu 22.04 VM 是交叉构建环境。

首版文字交互的预期路径是 `PC键盘/SSH终端 → RK kv_host stdin → RK CPU tokenizer → RK NPU逐层linear ↔ PCIe FPGA Attention/KV → RK sampling/detokenizer → kv_host stdout → PC终端`。PC 只传字符/显示，模型计算在 RK+FPGA；MobaXterm 只是终端/文件传输入口。**SSH 登录已验证，`kv_host` 及后续推理链尚未实现。**固定测试可改从文件读 prompt/写日志，不要求交互 prompt 预先存在 eMMC。

### Tutorial → Project 映射

| 教程或源码入口 | 实际教什么 | 本项目何时使用 / 不直接复用什么 |
|---|---|---|
| `01_start/01_start_linux/资料介绍.pdf` 与出厂测试 PDF | 默认系统、UART、两路以太网、TF、USB 等板级检查 | 首次无损盘点；出厂测试中的破坏性 `dd` 不运行 |
| `01_prepare/2_PuTTY安装与使用.pdf` | PC 通过板上串口观察 U-Boot/kernel | 首次启动和早期故障；PuTTY 只是终端，不是 FPGA 控制程序 |
| `03_restore_factory/1_Linux恢复出厂设置.pdf` | Windows RKDevTool/USB 驱动/整镜像与分区烧写 | **仅**在确定需要恢复/换镜像后由人操作，且需逐检查点确认 |
| `01_prepare/1_部署虚拟机环境.pdf` + Linux 系统篇 DOCX | Ubuntu VM、供应商 SDK、Buildroot/Debian 构建 | 有编译/重建系统需求时；日常 host 开发先验证现有系统能否直接部署 |
| Linux 设备篇 `08_TF`、`09_uart` 源码 | 交叉编译、设备名、用户态串口程序 | 建立 C/C++ build→copy→run 链；示例 `/dev/mmcblk1p1`、`/dev/ttyFIQ0` 均非固定事实 |
| Linux 设备篇 `01_wifi` 的 Rockchip Wi-Fi/BT 指南与 AIC8800 资料 | 无线驱动、`wlan0`/IP 故障诊断；其余是 Android 适配或 RF 产测 | 仅在确认无线芯片和网络故障时参考；这些 PDF 本身不证明 Wi-Fi/SCP，有线 SSH 由本次实板登录另行证实 |
| Linux 驱动篇 DOCX 与 `rk03-driver-demo.tar.gz` | 内核模块、字符设备、阻塞/异步 I/O | 读懂驱动结构；不是现成 PCIe 驱动，需内核 ABI 匹配 |
| RKNN/RKLL 课程与转换脚本 | PC 模型转换、板端 runtime/样例 | RK NPU 验证；RKLLM 整模型 demo 不能直接替代外接 FPGA Attention |
| `07_异构方案/AFC03_IMX415_PCIE_X1` | RK↔PH1A90 PCIe、SGDMA、视频流 | 学习枚举/BAR/driver/H2C/C2H；摄像头逻辑不是 QKV→Attention 服务 |
| `Wechat_ref` | 个人工程经验 | 补充故障线索，标 PRACTICAL REFERENCE，不能作为官方规格 |

## 3. Linux 镜像、启动与版本边界

入门教程所述 Windows 恢复工具是 `RKDevTool_Release_v3.36.zip`，驱动包 `DriverAssitant_v5.13.zip`，镜像示例 `mlk-AFC03-buildroot.img` 或 `mlk-AFC03-debian.img`（`03_restore_factory/1_Linux恢复出厂设置.pdf` §1）。异构课程本地还放有 `07_异构方案/mlk-AFC03-debian-v1.2.1.img` 和单独 `boot.img`；其 `readme.txt` 说 boot 改了 PCIe1/MIPI 相关设备树与驱动。这些不是同一个文件名/版本，不能任意混刷。`update.img` 是完整升级镜像容器；截图列有 loader、boot、rootfs 等分项镜像。Loader 负责上电启动/下载阶段，boot 含内核与设备树/启动资源，rootfs 是 Linux 用户空间；具体镜像分区表与签名/匹配关系须从目标版本核对，不能依据教学截图猜地址。

出厂 Buildroot 示例的底板 `ETH0` 对应 Linux `eth1`、底板 `ETH1` 对应 `eth0`（`02_test_board/1_Linux出厂系统测试.pdf` §1.3）；本板 Debian 实测接口名为 `end0`/`end1`。成员通过 MobaXterm 串口和 `kvdev` SSH 登录：板侧 `end0=192.168.137.101/24`（手工临时设置），PC Realtek“以太网”=`192.168.137.1/24`；`sshd` 监听22端口。`root` 密码锁定，SSH配置禁止 root 密码登录。网口/SSH在板卡重启后的自动恢复、SFTP传文件、rootfs空间和 eMMC 分区仍需验证。

Linux 设备篇 `01_wifi/官方资料/Rockchip_Developer_Guide_Linux_WIFI_BT_CN.pdf` 是 Rockchip 通用 V7.0.1（2024-04-16）：先驱动/`wlan0` 初始化，再配置 `wpa_supplicant` 或 Debian 的 NetworkManager，最后核对 DHCP/IP。它不针对这块 RK3576 板，也未提供本板 SSH/SCP 的成功记录。`厂家资料/AIC8800_USB_porting_guide_v1_2_20241021.pdf` 示例平台是 **RK3229 Android 10**，其固件/USB VID:PID 信息只能在确认相同芯片时用于排错；封面 Rev1.2 与页眉 Rev1.0 也不一致。其余 4 份 AIC8800 PDF 分别讨论 Android 蓝牙语音、异平台休眠唤醒或射频产测，均非首版 `kv_host` 部署步骤。本项目当前有线 SSH 已验证，Wi-Fi 尚未核查。

### NPU 工具链：教程演示与项目所需不是同一件事

`03_course/04-AFC03教程-RKNN人工智能篇/米联客2026版瑞芯微AFC03教程-RKNN人工智能篇.pdf` §2–3 的流程是 x86 Ubuntu 上 RKNN-Toolkit2 2.3.0、Model Zoo 2.3.0，将 YOLO ONNX 用 `convert.py ... rk3576 i8 ...` 转为 `.rknn`，板上 Debian/Python 运行 `yolov5.py --model_path ... --target rk3576 --img_show`。这验证“转换→runtime→输出”的**方法**，不是 Smol 线性层已经可运行的证明。随包视频 ZIP 的 README 自称 RK3588 验证，三核轮用/六线程视频吞吐设置不能搬到 RK3576 的 batch1 decode。

`03_course/05-AFC03教程RKLL人工智能篇/米联客2026版瑞芯微AFC03教程-RKLL人工智能篇.pdf` §1、§3、§5–7 展示 Hugging Face → RKLLM toolkit 1.1.4 W8A8 → `.rkllm` → C++ `llm_demo` 链接 `librkllmrt.so` → 板上按行输入 prompt 并流式输出。这很适合先确认 RK NPU/文字交互或做 RK-only 对照；**不能直接作为方案 C**。本地归档 `05-AFC03教程RKLL人工智能篇/rkll-toolkit2.rar!/rknn-llm-main.zip!/rkllm-runtime/Linux/librkllm_api/include/rkllm.h` 只见整模型 prompt/token/embedding 输入、生成回调和最后 hidden，未见逐层 Q/K/V 导出或外部 Attention 插入 API。结论是“本包接口未找到”，不是证明未来所有版本绝不可能支持。

同归档 `.../examples/Qwen2-VL-2B_Demo/deploy/3rdparty/librknnrt/Linux/librknn_api/include/rknn_matmul_api.h` 才是本地 MatMul API 线索：RK3576 K≤10240、K/N 有 dtype 对齐限制，M 可动态但 K/N 非动态，`rknn_matmul_run` 阻塞。Smol 的 D576、K/V192、FFN1536、vocab49152 静态维度满足列出的对齐约束，**不证明 LM Head 内存/效率、实际编译或 NPU执行**。归档中未找到本地可运行 MatMul demo；头文件对 `set_core_mask` 的 RK3588 注释不能照搬 RK3576。`rknn_api.h` 有查询 API/driver 版本、从 fd 创建内存、绑定 IO 与 cache sync 接口，但不证明 RKNN buffer 到 PCIe FPGA 零拷贝。方案 C 必须单独验证 RKNN 分图或 MatMul 路线，并与 CPU reference 对拍。

部署链要分清：PC x86 toolkit 负责转换；RK Linux 上匹配的 runtime/driver 加载部署模型；程序创建 context、准备 tensor/内存、同步、run、取 output。RKLL 示例的 `build-linux.sh` + CMake 使用 AArch64 交叉编译并链接 `.so`，其 `stdin` 交互可借鉴 host UI；最终 `kv_host` 需要逐层调用 NPU 与 FPGA，不能直接运行 RKLLM 完整模型。课程中的 `swap.sh` 会用 `dd bs=20M count=1024` 创建约 20 GiB 交换文件，未经存储容量/磨损评估不得执行。`06-AFC03教程opencv篇` 为图像/视频 GUI 学习资料，对首版文字终端 Demo 不构成依赖。

### PCIe 异构示例：可借鉴 transport，不能套用视频服务

`03_course/07_异构方案/AFC03_IMX415_PCIE_X1` 是当前**最接近方案 C**的随板工程。`.al` 工程目标是 PH1A90SEG324，配置 PCIe Gen2 x1/SGDMA，H2C/C2H 各一通道；RK3576 是 Root Complex，PH1A90 是 Endpoint。`IMX415_PCIE_X1/deploy/sgdma_drv` 中 `anlogic_pci_drv.c` 匹配 `1edb:abcd`，实现 PCIe device/BAR/SGDMA 字符设备；`cdev_sgdma.c` 涉及 H2C/C2H 数据通路，`cdev_ctrl.c` 提供 read/write/mmap/ioctl 用户入口。可以把**驱动层、枚举、BAR/SGDMA访问模式**作为起点，前提是先验证板上 bitstream、驱动与 OS/DTB 的匹配。`dts/rockchip/rk3576.dtsi` 和 `dts/rockchip/rk03/pcie.dtsi` 配置 PCIe1；源码树没有可直接加载的预编译 `.ko`，只有构建脚本和匹配内核的要求。SGDMA `version.h` 写 `2020.8.21`，不是“与2026镜像天然匹配”的证据。

但是 FPGA 顶层 `imx415_pcie_top.v` 把摄像头流送 C2H；H2C 进入通用 `sgdma_app` 回环/丢弃控制，**没有 QKV→QK/softmax/PV→output 的命令处理**。V4L2/摄像头/YOLO 不复用为项目协议。实际 `sgdma_ip_all.enc.v` 受加密保护，SGDMA核内部不能凭源码审完。未来需要新 Attention 消费者/状态机与逐层 host 调度，但本轮不写正式协议/RTL。

**不要直接运行 `pcie_setup.sh`。** 它可能补丁 DTB、重编译/装载内核模块、重绑 PCIe 控制器、操作 GPIO 和写 BAR 寄存器。其检测分支还可能把“任意 lspci 非空”当作 FPGA 存在，必须用**确切 `1edb:abcd` 和 BDF**验证。`diag_dma_test.sh`/`pcie_speedtest_gui.py` 写 `/dev/sgdma0_*` 且前者硬编码 BAR0=`0xf0200000`，但这份驱动源码生成 `/dev/ANLOGIC-PCI0_*`，RK3576 setup 会动态探测 BAR；未找到别名规则。字符设备 USER read/write 还有 `+0x80000` 偏移，而其他 BAR 访问路径使用原始映射；**不能假设 pread/pwrite 的 offset 与 `devmem BAR0+offset` 等价**。所有脚本/地址/节点需先实机对照，修改副作用经用户批准。无设备时应先看供电、bitstream上电先后、设备树 `pcie1` 和内核日志，再考虑重绑/改 DTB，不能盲运行“一键修复”。

异构课程 `readme.txt` 说 `boot.img` 要配 `mlk-rk03-debian.img`，但目录里实际文件叫 `mlk-AFC03-debian-v1.2.1.img`；何者已包含 PCIe1 设备树/驱动、与当前板系统是否同一内核均 UNKNOWN。`pcie1_enable.sh` 可原地修改 `/dev/mmcblk0p3`，且备份在 `/tmp`；不能把它当只读“检查脚本”。`build_drivers.sh` 可能调用包管理器及重建内核模块；`pcie1_rebind.sh` 会重新绑定控制器。不要在没有持久备份、镜像/内核/板版核对和用户授权时运行。MIPI 教程是另一条视频链路，不是当前 PCIe QKV 方案的替代实现。

这个例程的视频大包/持续流速率不回答方案 C 的瓶颈：每层16bit候选下发QKV 1920B、返回Attention output 1152B，batch1每token有30次串行同步。必须测**含通知/等待的单次双向往返**，再测依赖链；BAR映射/设备节点和 SGDMA 可用性都不是已实测事实。

`Wechat_ref/PL PS comm.txt` 为 Zynq PS–PL/AXI 的个人避坑文章：缓存同步、地址/对齐、复位顺序、跨时钟域只保留为 **PRACTICAL REFERENCE 的抽象检查项**；其中 Xilinx `Xil_DCacheFlushRange`、Vivado Address Editor、XPM_CDC 不能移植成 RK3576 Linux↔PCIe FPGA 操作规范。`Wechat_ref/LLMonFPGA.txt` 仅列外部项目名称，不提供可执行步骤或实测，不能作为本方案的驱动/烧录证据。

启动方式也不能机械套用视频工程：`yolo识别+自启动/rock/yolo/start_yolov5_pcie.sh` 在启动 YOLO 前**自动调用有副作用的 `pcie_setup.sh`**，并将日志写 `/var/log/pcie_setup.log`；`pcie1_enable.sh` 还可安装 systemd service。将来 `kv_host` 首版建议从交互终端手工启动并捕获日志，等驱动/版本/上电顺序稳定后才设计自启动，且不能直接复制该视频服务。

## 4. 高概率操作 SOP

统一交互：Agent 先完成软件准备 → 指明人要碰的具体连接/按键 → 写明应出现什么 → 让人发照片/日志 → 再判断下一步。**禁止把整套高风险步骤一次性要求用户执行。**

### SOP-LINUX-FLASH：仅在确需换镜像时

| 项 | 内容 |
|---|---|
| Prerequisites | 先记录现有 Debian 12 的 UART boot log、`/etc/os-release`、`uname -r`、板卡版号；确认为什么现有系统不够用，选定**同板版**完整镜像/hash、数据备份与回退方案；明确整镜像会覆盖原系统/数据；用户明确同意后才走烧录 |
| Human action | Windows 安装教程指定 USB 驱动；在 RKDevTool v3.36 选“升级固件”与经核对的镜像；将 Type-C **SOC PORT/下载口**接 PC 主机（不是 Ubuntu VM，也不是仅供 UART 的串口口），按教程图在上电前按住 MASKROM 键并上电；把接口照片和 RKDevTool 设备状态发给 Agent，**此检查点前不点升级** |
| Agent/software action | 静态核对镜像文件、容量/hash、板版、工具识别状态和备份；检查不误选分区表/地址。确认后才单独引导用户启动升级，不代替用户按键/插线 |
| Expected / verification | 教程显示“发现设备”/设备为 LOADER 的画面；升级完成工具显示 100%。随后仍须 UART 启动到 shell、核对新 OS/kernel 与可访问存储，100% 本身不足以证明可运行 |
| Common failure / recovery | 无设备：先核对数据线、SOC PORT、USB 驱动/主机归属、按键时序，再看 RKDevTool 截图；镜像不匹配或分区失败：**停止**，保留日志，不试随机地址/其他分区。仅按原教程/技术支持确认恢复步骤 |
| Source | `03_restore_factory/1_Linux恢复出厂设置.pdf` §1–2；异构目录 `readme.txt`。教程另一条 Linux `upgrade_tool`/“boot”键路径也有，但此处不混用 |

教程中“分区烧写”提及手动填写地址，且正文将模式拼为 `LOAFER`、截图为 LOADER；这是文本错误/版本差异，**不把手工分区写入列为首选 SOP**。教程给出的 `/home/linux/rk3576/...` 是示例路径，不是本地已存在 SDK。当前板已经运行 Debian 12；是否需要更换为异构例程的专用镜像，取决于后续驱动/runtime核验，不因教程出现新镜像就重刷。

### SOP-UART-RK3576：最早的可观察性

| 项 | 内容 |
|---|---|
| Prerequisites | 参照 PuTTY 教程的板卡串口图，区分 **RK3576 串口 Type-C** 与 SOC PORT/FPGA UART；PC Windows USB 设备归主机而非 VM，设备管理器确认新 COM 号（COM7 仅截图示例） |
| Human action | USB-A→Type-C 插 PC 与板上 **串口口**；PuTTY 或 MobaXterm 选 Serial、刚识别到的 COM，按教程设 `1500000` baud；先打开终端，再上电/复位 RK 板；把板上接口照片、COM 截图和首段日志发回 |
| Agent/software action | 从 U-Boot→kernel→login/root shell 顺序分析；若乱码先核对 1500000 与 COM/虚拟机 USB 占用；若黑屏核对电源、线与实际端口，不先认定系统损坏 |
| Expected / verification | 教程图示 U-Boot/kernel 输出，Buildroot 示例最后进入 root shell；本板已通过 MobaXterm Serial 获得 Debian root shell。终端窗口打开本身不证明启动成功。Serial 8N1/无流控可作为初始设置，但 PuTTY 教程正文只明示波特率，实际参数应记录在团队设备日志 |
| Source | `01_prepare/2_PuTTY安装与使用.pdf` §3.2；Linux 设备篇 `09_uart/uart_test.c` 的 8N1、`/dev/ttyFIQ0` 只用于另一个用户态发送示例，不能反推独立控制通道 |

### SOP-FIRST-BOOT：无损盘点

Prerequisites：先确认 UART 能读、知道登录身份。Human action：开板、提供完整 boot log/提示符；若要求输入凭据，由人输入，不在日志分享密码。Agent/software action：仅建议读取 `cat /etc/os-release`、`uname -a`、`free -h`、`lsblk -f`、`ip -br addr`、`lspci -nn`、`dmesg | tail` 等，不先改镜像、device tree 或网络配置。Expected result / verification：得到 OS/kernel、内存、存储和 PCIe 枚举快照，记录命令/输出/时间。Common failure：若停在 U-Boot/kernel panic、提示符不是预期或命令不存在。Recovery / next diagnostic：定位最后成功阶段与错误、换镜像适配命令，不盲刷。Source：入门出厂测试 §1.1/1.3；Linux 设备/驱动课程。

### SOP-FILE-TRANSFER：从 Windows 源码到板上程序

Prerequisites：板上已登录、网络/存储可用，目标路径有空间，确认板上架构/OS/libc/runtime。Human action：若无网络，由用户接 TF/U 盘并反馈插入前后设备列表；SSH 已通时仅确认板 IP/账号及可写路径。Agent/software action：在 PC 写源码/构建脚本 → 选匹配 AArch64 工具链或板上编译 → 生成 ELF/动态库 → 查架构与依赖 → 经获授权连接 SCP/SFTP（若 SSH 已启用）传输；离线时先 `lsblk -f` 辨识，再挂载/复制，**不沿用硬编码 `/dev/sda` 或 `/dev/mmcblk1p1`**。RK 上 `chmod +x`、检查 `ldd`/库路径、执行、保存 stdout/stderr/dmesg。Expected result / verification：程序打印版本与最小自检、记录制品hash，链条每环留日志。Common failure：`Exec format error`、有文件却 `not found`、权限或缺库。Recovery / next diagnostic：分别查架构、动态加载器/库、`chmod`/挂载选项与磁盘空间，不立刻换系统。Source：Linux 设备篇 §8–9 的源码/环境脚本；驱动篇 §1.2 的 TF 路径仅示例。

现成例子的具体产物链：Linux 设备篇 `rk3576-mlka-env.sh` 设 AArch64 GCC 10.3 路径，`08_TF`/`09_uart` 下 `make` 生成用户态测试程序，复制到板上执行；但 `09_uart/Makefile` 还夹带内核模块构建与本地清理命令，不能原封不动用于 `kv_host`。RKLL 归档的 `build-linux.sh`/CMake 生成 `llm_demo`，需连同 `.rkllm` 与匹配 `librkllmrt.so` 部署；其每行 stdin→文本 stdout 交互模式可以借鉴，计算结构不能借用。PCIe `build_drivers.sh` 目标是内核 `.ko`，版本须对上板 kernel/vermagic，与普通用户态 ELF 的部署门槛不同。

本板当前已用 `kvdev@192.168.137.101:22` 登录 SSH，PC“以太网”是 `192.168.137.1/24`；前者由 `ifconfig` 临时设置，重启持久化尚待验证。传输首选 SCP/SFTP 到 `/home/kvdev`，但**实际文件传输还没有测试**。通用形式是 `scp <本地二进制> <账号>@<实际板IP>:<确认可写目录>/`；传后在 RK shell 检查文件、权限与依赖，再运行程序。MobaXterm 是远程终端/传输入口，真正调用 NPU/FPGA 的是 RK 上的 host 程序。

### SOP-RKNN-RUN：先证明 NPU，再替换 Smol 算子

Prerequisites：确认 RK3576 NPU driver、runtime/Toolkit兼容组合与部署模型版本；板上若有 Python，核对 `python3 --version` 与 wheel 标签。Human action：负责板子连接/供电/必要镜像变更并发版本/运行日志。Agent/software action：先用课程 RKNN YOLO/RKLLM 整模型示例建立最小 **NPU 确实执行** 证据（runtime/driver 查询、输入输出与计时）；取得相应 MatMul runtime/demo 后，以**真实 Smol 矩阵 shape、M=1** 做独立微基准，记录初始化、权重装载、输入布局/copy、同步、run、取回输出、CPU reference 误差和峰值内存。Expected result / verification：确认执行设备、API/driver版本、逐阶段耗时与数值误差；`LM Head[49152,576]` 不得仅凭头文件认定可高效运行。Common failure：wheel/Python ABI 不符、runtime/driver 不匹配、shape虽对齐但编译失败/过慢、只有整模型文字输出。Recovery / next diagnostic：记录确切版本/错误码/shape、最小化测试，不改B/U/M变量；仅整模型输出不算分层 MatMul 证据。Source：RKNN教程 §2–3、RKLL教程 §1/3/5–7 与本地 MatMul API 头；未冻结项见 NPU-001～004/NUM-001。

### SOP-PCIE-CHECK：先证明链路，再讨论协议

Prerequisites：板版、镜像与相匹配 FPGA bitstream/驱动，先查脚本副作用。Human action：完成线缆/上电/JTAG（如需）并发板卡/串口日志。Agent/software action：先只读 `lspci -nn`、`lspci -vv -s <BDF>`、`dmesg`、设备节点/sysfs BAR，精确核对 vendor/device/BDF/绑定；**仅在核实副作用和得到批准后**做 H2C+C2H 校验与小包延迟，最后测 30 层依赖。Expected result / verification：目标 `1edb:abcd` 在预期 RC 下、BAR合理、驱动绑定并生成与源码一致节点、双向数据校验通过。Common failure：任意设备被误认FPGA、只通C2H视频、节点名/BAR偏移不符、脚本声称成功而未双向校验。Recovery / next diagnostic：先留 `dmesg`/`lspci -nnvv`/sysfs resource/节点列表，核对 FPGA 配置先后；修改 DTB、重绑 RC、`insmod`、`devmem` 写入单独批准与版本匹配。Source：异构 PCIe 教程、`imx415_pcie_4k.al`、`sgdma_drv`、`pcie_setup.sh`/诊断脚本；视频流例程不是 Attention RTL。

## 5. 人类与 Agent 的分界

| Agent 可直接做（本地/取得对应访问权后） | 必须由操作者完成或确认 |
|---|---|
| 源码/Makefile/CMake/脚本、模型转换方案、静态驱动分析、golden、编译、日志诊断、准备命令与检查表 | 插拔 SOC PORT/串口/JTAG/网线，板卡上断电与按实体键/拨码、核对板上丝印与 LED/COM、备份重要数据、确认/执行危险烧录或分区操作 |

对危险步骤，Agent 只给当前一个检查点：**请做什么 → 正常应看到什么 → 不应继续做什么 → 请回传什么**。用户回传后再判断，不自动跳过人机确认。

## 6. 版本/环境矩阵（区分教程与实板）

| 组件 | 资料中出现的版本/状态 | 当前证据边界 |
|---|---|---|
| 入门/课程 | 米联客 REV2026，2026-03 多篇 | 文档内部分截图/命令可能来自其他 RK 平台，优先核对 AFC03 板图与现有工程 |
| PC 开发 VM | Ubuntu 22.04；VMware Workstation 17.6.3 | 推荐的交叉构建环境，预制 VM 未在本地目录找到；不是 RK 板 OS |
| 供应商 SDK | `mlk-sdk-3576-v1.1.0.tar.gz` | 教程要求从官网获取；本地未发现，不可假设路径 `/home/uisrc/...` 存在 |
| AArch64 交叉 GCC | 10.3.1（课程 `rk3576-mlka-env.sh`/Buildroot 文档） | 要与当前 Debian 12 镜像/libc匹配；kernel 未记录 |
| 教程出厂 OS / 本项目实板 | 教程称默认 Buildroot；成员实测 Debian 12 bookworm | `kvdev` SSH已登录，镜像发行号、kernel与驱动仍未知；不把本地 Debian 1.2.1 文件当作已烧镜像 |
| 本地异构镜像 | `mlk-AFC03-debian-v1.2.1.img` 与单独 `boot.img` | 文件存在不等于已烧入；与 SDK 1.1.0、驱动 ABI 是否兼容 UNKNOWN |
| Windows 烧写工具/驱动 | RKDevTool v3.36；DriverAssistant v5.13 | 资料示例，不证明本机已安装或当前板驱动状态 |
| RKNN Toolkit/Model Zoo | RKNN教程 2.3.0 | 课程第04目录未见所需 toolkit/model zoo ZIP，需另取得并核对 hash/版本 |
| RKNN 板上 Python | 教程 Debian CPython 3.8 wheel；异构目录另有 Lite2 2.3.0 `cp311` wheel | 3.8/3.11 ABI 不兼容，实际板 Python/runtime 必须查后选，不能混装 |
| RKLLM | 教程与 README 要求 toolkit/runtime 同为 1.1.4、W8A8 示例 | 归档中未见教程提及的 toolkit 1.1.4 wheel；板上 driver/库版本未知 |
| NPU driver 与 PCIe driver | 当前板上的实际版本 UNKNOWN | `RKNN_QUERY_SDK_VERSION` 可查 API/driver；PCIe 模块须与内核 ABI 匹配 |
| PCIe随板工程 | PH1A90SEG324、Gen2 x1、`1edb:abcd`、RK3576 RC/FPGA EP | 工程源码事实，当前板枚举、BAR、模块节点与双向延迟未实测；异构 Debian image/boot.img须配套 |
| SGDMA源码头 | `deploy/sgdma_drv/version.h` 标 `2020.8.21` | 源码版本号，不证明预编译模块与现有 Debian 1.2.1 kernel 匹配；目录未见现成可加载 `.ko` |

### 明确冲突，不静默合并

| 两份资料各说什么 | 当前处理 |
|---|---|
| 入门资料：厂带 Buildroot、一般无需刷新；异构 PCIe 教程：用专用 Debian + boot 组合 | 实板已运行 Debian 12，但具体镜像未知；先核对当前 PCIe/NPU driver/runtime，再判断是否需要更换镜像 |
| 入门烧录 PDF：`mlk-AFC03-debian.img`；异构 `readme.txt`：`mlk-rk03-debian.img`+boot；本地：`mlk-AFC03-debian-v1.2.1.img`+boot | 同板不同示例/版本，不能据文件名自动拼接；请板卡供应商或匹配发行说明确认配套 |
| 设备篇 TF 示例 `/dev/mmcblk1p1`；驱动篇示例 `/dev/sda` | 两者都是示例名，实机 `lsblk -f` 后再确定，任何 `dd` 写盘均不由教程自动授权 |
| RKNN教程板端 cp38；异构 wheel cp311，RKLL教程称含 1.1.4 wheel 但归档未见 | 以板上 `python3 --version`、runtime/driver查询与确切 wheel 文件为准；缺包要取得兼容发行物，不混装 |
| RKLL PDF 称 `rkllm_api.h`；归档实际 `rkllm.h`，部分转换命令/文件名也不一致 | 编写时以本地实际头/脚本及 SDK 版本为准，教程只用于理解调用链 |
| PCIe `diag_dma_test.sh`/GUI 用 `/dev/sgdma0_*`，驱动源码生成 `ANLOGIC-PCI0_*`；诊断 BAR0 固定而 setup 动态探测 | 源码/实机设备节点与 sysfs resource 优先；原诊断脚本先审后改，不直接运行 |
| 驱动篇把 `volatile` 解释为多核同步手段，并称定时器回调在进程上下文 | 属教学不严谨之处，生产驱动以内核 API/实际源码和测试为准 |

### 常用只读诊断速查

| 想确认 | 先试的只读入口 | 结果说明 |
|---|---|---|
| OS / kernel / 可用内存 | `cat /etc/os-release`，`uname -a`，`free -h` | 辨 Buildroot/Debian、内核 ABI、实际 RAM；不能用教材版本代替 |
| 分区和剩余空间 | `lsblk -f`，`df -h`，必要时 `mount` | 决定可写部署目录；不运行原始设备写入测试 |
| 网络/SSH | `ip -br addr`（或镜像有的 `ifconfig -a`），`ss -ltn` | 网口名/IP与SSH监听要实看；硬件ETH0/1映射可能随镜像改变 |
| USB/TF | `lsusb`（若已装），`lsblk -f`，`dmesg` | 插入前后比较设备变化，不照抄 `/dev/sda` |
| PCIe/驱动 | `lspci -nn`、目标 BDF 的 `lspci -vv -s <BDF>`、`dmesg`、`ls -l /dev/ANLOGIC*`（如存在） | 只将 `1edb:abcd`/实际 BDF/匹配节点算目标，不能以任意 PCIe 设备代替 |
| ELF 与动态库 | PC `file <binary>`，RK `ldd <binary>`（若镜像提供）、`ls -l` | 排查错误架构、加载器/库版本、权限；不在不可信二进制上盲执行 |
| NPU | 在**确有匹配 runtime 的测试程序中**调用 `RKNN_QUERY_SDK_VERSION` | 记录 API/driver，而不是猜测 wheel 与板上内核兼容 |

成员已执行 `/etc/os-release`、`ip`、`ss` 等基础诊断；其余命令仍是后续只读检查建议。

## 7. 仍需实机确认

以 [UNKNOWNS](UNKNOWNS.md) 为唯一活动清单。当前仍需确认精确板版与镜像、kernel/驱动 ABI、`end0` 地址与 SSH 的重启持久化、SFTP传输、NPU runtime、PCIe枚举与双向延迟、Smol真实shape性能，以及 Attention RTL资源和质量。已有 Debian 12/串口/SSH 证据不替代这些测试。

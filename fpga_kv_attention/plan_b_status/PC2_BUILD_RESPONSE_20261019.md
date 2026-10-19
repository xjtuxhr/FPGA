# 给 PC2：Plan B 完整构建与 JTAG 交接（2026-10-19）

这版是 `functional_b64s3`（`MAX_T=64`、`SCORE_SHIFT=3`）加 STATUS/CONTROL 与软复位的 FPGA bit。用户已确认通过 JTAG 下载 `attention_planb_full.bit`；以下构建证据来自本地文件，板端 BAR、PCIe 和恢复结果仍待 PC2 实测。

| PC2 问题 | B 的核对结果 |
|---|---|
| 旧日志是不是完整综合/P&R？ | 10-18 工程先完整综合/P&R；其最后交付的 `attention_holdfix.bit` 却来自 `import_db attention_final.db` 后 `fix_hold`，不能作为“从头完整重建”的证据。该旧 bit 未烧录。 |
| 新 bit 是否包含 `kv_app_status` 和 TOP 接线？ | 新 `attention_gate.area` 与最终 `attention_planb_full.area` 均列出 `u_kv_app_status`；综合日志分析了 `kv_app_status.v`。组装脚本把 `app_soft_reset`、状态输入及完整 AXI-L 地址接到 `imx415_pcie_top.v` / `sgdma_app.v`。这是 RTL/网表证据，实板 BAR 行为仍待读回。 |
| BAR0 user 基址 `0x80000` 与旧 `[31:8]==0` 是否匹配？ | 不保证匹配。驱动 `anlogic_pci_lib.h` 定义 user 基址 `0x80000`，`anlogic_pci_cdev.c` 为 user 节点设置该基址。现改为仅接受 `0x000000A4/A8` 与 `0x000800A4/A8` 两个完整地址窗口；其余窗口拒绝。加密 SGDMA IP 向 TOP 输出哪种地址仍待板测。 |
| 是否重新完整构建并烧录？ | 是：10-19 新工程从冻结 154 个输入重建，TD 新综合生成 `attention_gate.db`，新的物理脚本只导入该 gate DB 并执行 `place`、`route`、`fix_hold`、`bitgen`。用户已报告 JTAG 下载成功；尚无 TD 下载日志/截图。 |

## bit 与构建证据

- bit：`E:/KVmix/fpga_attention_ddr_planb_full_20261019/attention_planb_full.bit`
- SHA256：`A9560E762C5C2DBF89CB4C10346CA8C2A849FB2DA7CFE4D4DF7F93A4A5AB2887`；大小 4,850,323 字节。
- TD 工程：`E:/KVmix/fpga_attention_ddr_planb_full_20261019/attention_ddr.prj`；综合脚本 `synth_functional.tcl`，物理脚本 `physical_clean.tcl`。
- 日志：`td_20261019_212614.log`（综合）、`td_20261019_213350.log`（导入新 gate DB → place → route → fix_hold → bitgen）。最终报告：`attention_planb_full.area`、`attention_planb_full.timing`、`attention_planb_full_check.timing`。
- 最终 routed 报告：setup WNS +0.306 ns、hold WNS +0.020 ns，TNS 均 0，STA coverage 99.20%；LUT6 22,155，slice 27,171，ERAM 98，DSP 4。`check_timing` 仍含时钟/IO 约束警告，不能视作全路径签核。
- 离线仿真：`kv_app_status`、`planb_soft_reset_cdc`、RESET CDC 62 个向量通过；覆盖两种地址窗口及其他窗口拒绝。

## 请 PC2 在独占窗口记录的实板检查

1. 在用户确认 JTAG 下载结束后，由 PC1 从 RK 的 **root 串口/控制台**执行 `/usr/local/sbin/pcie1-recover.sh`，保存执行输出；PC2 随后检查 PCIe 枚举及四个设备节点。既有恢复决定指出 `kvdev` 无 sudo 权限。B 当前电脑对两条已知 RK SSH 地址均超时，不能代替团队声称已恢复。
2. 对 `/dev/ANLOGIC-PCI0_user` 以 4B 对齐方式读取逻辑偏移 `0xA4`，记录原始 32-bit 数值。正常 DDR/桥/端点空闲时预期 READY bit4=1；若为 0，按位区分 BUSY/FAULT/ERR，不要立即写 H2C。读 `0xA8` 应返回 0。这里的逻辑偏移由驱动加上 user 基址 `0x80000`。
3. 若 READY=1，在**一个** H2C 进程内完成单次 RESET、OP_TEST 和空闲时 CONTROL `0xA8` 写 `0x00000001`（SOFT_RESET）的检查，记录 READY 是否重新出现及 RESET/OP_TEST 能否重入，保存每次 STATUS 与 C2H 帧结果。若现有工具必须启用第二个 H2C 进程，先由 PC1 再执行一次恢复。DONE bit0 只是 FPGA 交出最后一个 C2H beat 的标记，不代表 Linux 读取完成。
4. 在负例测试之前，按团队约定保持一次 recovery 只运行一个 H2C 进程；`deadline_enforced=false`。`SESSION_ABORT`/ERR=7 语义还未冻结，请先与 B 对齐再测。不要把写后 `wait_ready()` 当成 H2C 写前 READY 门控。

本文件记录“用户报告 JTAG 下载成功”，并不冒充自动读回或板端功能通过。请回传 PCIe 恢复日志、`0xA4` 原始读值和第一轮 RESET/OP_TEST 结果，以确认新 bit 与 BAR 地址路径。

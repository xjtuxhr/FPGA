# B 功能版 Attention + DDR：源码与 TD 构建输入

本目录固定了 2026-10-14 功能 bit 对应的 **B 模式**源文件：`MAX_T=64`、`LAYERS=30`、`SCORE_SHIFT=3`、FP16 KV 存储、候选 Q8.8 运算。器件为 PH1A90SEG324，TD 版本为 6.2.200067。参照 bit `attention_ddr.bit` 的 SHA256 为 `C510C4FBA08D76B82FC5B1773BF460E60E920F12488627FF4BC64D09A9FAB378`。该 bit 本身没有入库。

这里的 `rtl/` 是当时实际工程中的 17 个 B 侧 Verilog 文件；`patches/` 是相对已验证 DDR-only 工程的三处接线/时序差异，避免复制整份厂商源文件；`configs/` 保存 DDR、PCIe、PLL 的 IP 配置及板级约束；`td/` 保存当时 TD 工程、综合设置与综合/布局布线 Tcl 模板。`manifest.json` 固定 154 个 TD 输入文件、137 个外部基础工程 TD 输入、284 个基础工程文件（含未列入 TD 文件表的 DDR ROM）及关键构建文件的 SHA256。

## 重建源码工程

需先取得 **未修改的** `fpga_ddr_diag_20261014` DDR-only 基础工程（含厂商生成的 DDR/PCIe/SGDMA IP、ROM 和厂商模块）。这些外部文件受 `manifest.json` 的 284 个哈希约束，没有随仓库上传。只导入 `ui_ddr.sv` 代替 `ui_ddr.ipc` 不能视为同一 TD 工程；DDR IP 的 `.ipc`、`.adc`、`.sdc` 应按工程配置导入，并使用同一 T13 100 MHz 参考时钟，不重复约束管脚。

在 PowerShell 中，先核对基础工程，再生成一个**全新目录**（脚本拒绝覆盖）：

```powershell
python fpga_kv_attention/functional_b64s3/assemble.py --base E:/KVmix/fpga_ddr_diag_20261014 --check-only
python fpga_kv_attention/functional_b64s3/assemble.py --base E:/KVmix/fpga_ddr_diag_20261014 --out E:/KVmix/attention_ddr_rebuilt --td-root C:/Anlogic/TD_Release_2026.1_SP2.200.067
```

第二条命令复制基础工程、叠加 RTL/补丁/配置、填写 TD 路径，并核对重建后全部 **154/154** TD 输入的 SHA256。基准工程不满足哈希时会停止；这有助于发现不同的 IP 版本或已有改动。六份 TD 配置模板回填到历史路径后也与原工程逐字节一致。生成工程的位置不同，因此其 `.al`、Tcl 等文件中的绝对路径随位置改变。

运行 TD 前检查 `attention_ddr.al` 的源/IP 列表、DDR 管脚约束、许可证与实际板型。综合和布局布线使用生成目录下的脚本，顺序如下：

```powershell
& 'C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe' 'E:/KVmix/attention_ddr_rebuilt/synth_functional.tcl'
& 'C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe' 'E:/KVmix/attention_ddr_rebuilt/physical_functional.tcl'
```

第二步会生成新的 `attention_ddr.bit`。必须审查完整综合/布局布线日志、时序、资源与 bit 哈希；**154 个源输入相同不保证不同目录/重跑的 bit 逐字节相同**。脚本不会自行运行 TD、烧录或访问板卡。

## 已有证据与边界

原功能工程的 TD 报告：LUT6 22032、Slice 27073、ERAM 98/272、DSP 4/240；setup WNS +0.257 ns、hold WNS +0.020 ns、TNS 0、STA 覆盖率 99.19%。仍有未约束的旧摄像头外部路径，不能视为全工程签核。后续实板已完成 CPU/HF 输入的单层对拍、不同 K/V 的层间隔离与非空缓存 RESET；详见[当前进度](../../docs/TEAM_PROGRESS_AND_NEXT_STEPS_20261018.md)。这些板测不等于 NPU v40 新输入已经过 FPGA。

PC1 另补 `summary(1).json` / `run(1).log`：声明 8 个位置、24 次 NPU 调用，状态为 `PASS_REAL_NPU_QKV_CAPTURE_V40`，manifest SHA256 `C9791AE59630064B97B9593E6CCF0E2EBB2944E9A30DBB14E96493E70DC4276C`。两文件哈希保存在本目录 manifest；它们只证明 **PC1 声明的 NPU QKV 捕获运行**，文件自身明确 `fpga_executed=false`、`pcie_executed=false`。v40 的 FPGA/PCIe 实测还需 PC2 在授权窗口中完成，不能用这份日志替代。

PC2 的《H2C 超时与恢复门槛》补充（本地文件 SHA256 `B6BE7AC93B0B483AAA16F99CE637830CCF6A404CFD1C28FC8FF845B1F48AB705`）给出实板反例：请求 0.5 s deadline 的阻塞 H2C 写约 9.998 s 才返回；同一次恢复后的第二个 H2C 进程可能失败。因此 `deadline_enforced=false`、`session_reusable=false` 仍应按已证事实处理。文档建议短期显式接受 best-effort H2C 且 fail-stop（方案 A），长期评估状态寄存器与驱动修复（方案 B）；**这是一项待团队选择的运行策略，不是本次 RTL/TD 提交已解决的能力**。PC2 文档在 v40 输入交付前写成，其中“尚无 NPU capture”的旧描述已被 PC1 的新交付更新；本批 NPU 输入的 FPGA 回包仍未实测。

本目录不含厂商加密 IP、生成的 DDR core、模型/原始向量、bit、许可证或板上运行日志。旧算子库中的 `v2_endpoint.v` 及 Attention RTL 可能比本功能版本早；以此目录和 SHA256 清单为准。

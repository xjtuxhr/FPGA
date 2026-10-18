# Plan B 应用状态寄存器候选版（待 PC2/B 定稿）

本目录在已冻结的 `functional_b64s3` B 模式（`MAX_T=64`、`SCORE_SHIFT=3`）上增加 BAR 状态和端点软复位。基准功能 bit 不变；这里的代码及新 TD 工程是候选版，尚无新 bit、烧录或实板恢复证据。

PC1 补交的 `pc1_host_bridge_source_snapshot_20261018.zip` SHA256 为 `061FF484B9A955639FD0B9F1F3597CECBF1AE41433B51ED9D66007124903495C`；快照内 73 个文件与 manifest 哈希全部匹配。其 host bridge 拥有 v2 framing/seq，PC2 DeviceOps 拥有 SGDMA；正式插件仍要求 `deadline_enforced=true`，本次快照和 PC2 当前 adapter 均未证明此能力。该快照不是 BAR 映射定稿，也没有板端测试结果。

PC1 的 `Pc2SgdmaBridge.exchange()` 实际调用次序为 `device.write(request)` → `notify()` → `wait_ready(seq)` → `read_exact()` → v2 回包身份校验。因此 **写前** BAR READY 轮询应放在 PC2 `DeviceOps.write()` 内或其前置入口，不能只放到当前写后才调用的 `wait_ready()`。DONE 不带 seq，仅可作为进度提示；PC1 仍须核对 C2H 帧的 CRC、seq、op、layer、position，不能用旧 DONE 充当本次完成。

## 候选寄存器

PC2 提议通过 `/dev/ANLOGIC-PCI0_user` 对 BAR0 作对齐 4B 的 `pread/pwrite`，逻辑偏移如下；AXI-L 读不清零。

| 偏移 | 方向 | 字段/写值 | 当前候选语义 |
|---|---|---|---|
| `0xA4` STATUS | 32-bit read | `[0] DONE` | C2H 最后一个 AXI-ST beat 已被 SGDMA 接收后锁存；下一次 H2C 接收或软复位清零；**不代表 Linux DMA read 已完成** |
|  |  | `[3:1] ERR` | 端点错误码 0–6；7 为 DDR ready 曾就绪后丢失、非法 CONTROL 写、或复位时 AXI/Attention 正忙；首错锁存，软复位清零 |
|  |  | `[4] READY` | DDR ready、跨域桥释放、端点空闲、Attention/AXI 空闲且无锁存 FAULT/复位；这是**写前状态快照**，不承诺写入途中不会背压或阻塞 |
|  |  | `[5] FAULT` | 锁存 FPGA 应用故障；需停会话并处理，读不清除 |
|  |  | `[6] BUSY` | 端点非空闲、Attention engine 工作或软复位正在进行 |
| `0xA8` CONTROL | 32-bit write | `0x00000001` SOFT_RESET | 当 engine 不忙时，持续 16 个 `usr_clk` 周期复位端点和两侧 FIFO，清 FPGA 会话/KV 历史及锁存状态；**不复位 PCIe/SGDMA 或 DDR 控制器** |
|  |  | `0x00000002` SESSION_ABORT | **待 PC2 确认**：候选为清端点/FIFO/KV 历史并留下 `FAULT=1,ERR=7`；随后需显式 SOFT_RESET 才可重入 |

CONTROL 要求 4 字节 strobe 全 1 且写值严格等于 1 或 2；其他写法锁存 `FAULT/ERR=7`。若 Attention engine 忙，不强行截断已发出的 AXI4 burst，而是拒绝 CONTROL 并置 `FAULT/ERR=7`。目前仍要求 host 确认没有活动的 H2C/C2H 进程再作复位；BAR 控制不会取消阻塞中的 Linux `write()`，也不会替代 SGDMA 驱动中断/描述符恢复。异步状态通过两级寄存器跨到 `usr_clk`，读到 READY 后状态仍可能改变。

DDR 上电后若从未校准成功，这版只报告 `READY=0`，不会凭等待时间自行置 `FAULT`；PC2 必须以有界等待失败处理。它当前也未把 `ddr_init_cal_err[7:0]` 直接映射进三位 ERR，这需要双方确认编码后再加。DDR 曾 ready 后丢失则锁存 `FAULT/ERR=7`。

**需要 PC2/B 冻结**：`SESSION_ABORT` 的确切用途、ERR=7 的归类、busy 时是否仅拒绝、BAR0 user 节点上的写 strobe/偏移、复位与在途 DMA/AXI 的互斥约束。冻结后应同步更新 PC2 binding/host mock，再生成正式 bit。PC1 的正式 plugin gate 保持关闭；`deadline_enforced=false`、一次 recovery 只跑一个 H2C 进程，直到 PC2 的负例证明有界中止和跨进程可复用。

## 构建与离线证据

`assemble.py` 会先校验并重建冻结的 154 输入功能工程，在全新目录叠加本目录 3 个 RTL 文件、TOP/SGDMA BAR 接线和 TD 文件清单；不启动 TD、不接触板卡。例：

```powershell
& 'C:/Users/47736/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' fpga_kv_attention/plan_b_status/assemble.py --out E:/KVmix/fpga_attention_ddr_planb_candidate_v2_20261018
```

`sim/kv_app_status_tb.v` 已覆盖上电、READY、DONE、忙时拒绝复位、端点错误、非法 CONTROL、SESSION_ABORT 候选和 DDR ready 丢失；`sim/planb_soft_reset_cdc_tb.v` 已覆盖旧 ACK 在 C2H FIFO 中时的软复位冲刷、坏 CRC 后的故障恢复，以及新 RESET 的单帧 ACK/seq/DONE。冻结版 RESET CDC 62 个向量在新 wrapper（soft_reset 绑 0）下全部通过。以上仅为离线仿真，不是 TD 时序签核或板上证明。

2026-10-18 的**候选工程离线构建**位于 `E:/KVmix/fpga_attention_ddr_planb_candidate_v2_20261018`。TD 6.2.200067 联合综合、布局布线和 bitgen 完成；先前常规 `route` 后 hold WNS 为 −0.015 ns，追加 TD 官方 `fix_hold` 命令后最终 routed 报告为 setup WNS **+0.442 ns**、hold WNS **+0.020 ns**、两者 TNS 0，STA coverage 99.20%；资源为 LUT6 22088、slice 27036、ERAM 98/272、DSP 4/240。候选 `attention_holdfix.bit` SHA256 为 `531DE07D8ACAE24E9C01D81873EDAC9E4348E0C217CD203184B16F2475B380C5`。**没有烧录或板测**；旧功能 bit 仍是已知实板基线。

该次 TD 构建曾对新文件的 `CompileOrder` 与一个原文件重复发出警告；已把 `assemble.py` 的新文件顺序改为唯一的 205，并验证由它重建的五个关键 RTL/接线文件与该次构建逐字节相同。新脚本和 `td/holdfix_candidate.tcl.in` 为后续无顺序冲突的重建入口；不应假定重新构建的 bit SHA 会相同。时序检查仍报告原相机/PCIe 工程中的 PLL 频率提示、未约束旧摄像头路径等问题，需单独复核；上述正裕量不能代替板级功能、跨进程恢复或硬 deadline 证据。

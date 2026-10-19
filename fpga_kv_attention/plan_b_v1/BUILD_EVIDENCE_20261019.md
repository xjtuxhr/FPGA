# Plan B v1 Attention/DDR 构建证据（2026-10-19）

状态：**离线构建与仿真完成；未烧录、未在新 bit 上验证 BAR/DDR/Attention。**

## 输入与范围

- 源码目录：`fpga_kv_attention/plan_b_v1/`；构建脚本 `assemble.py` 从冻结的 `functional_b64s3` 及前版集成工程重新组装完整 TD 工程，保留 `MAX_T=64`、`SCORE_SHIFT=3`。
- PC2 冻结文档：`PC2_B_INTERFACE_FREEZE_V1_20261019.md`，SHA256 `C9B1FDF360B3A5F4EC2DF23D4981D7A5F9AAACC724D9F1E6D49C3D3F58C84DBD`；PC2 原始 `planb_status_ctrl.v`，SHA256 `17059D842F14A9DE80B50BFDAC7D507F85511379FDE1FFFF8C50288FC0366019`。这两文件在 PC2 后续总包中逐文件哈希相同。
- B 对控制模块只改了故障锁存后的 START/DONE 行为：`FAULT/ERR` 不被下一拍误清，必须 SOFT_RESET。新增 `planb_reset_guard.v`、H2C 首拍 READY 门控、跨域 quiesce 请求/应答、AXI outstanding 计数和响应完成脉冲。
- BAR0：`0xA4` STATUS、`0xA8` CONTROL、`0xAC` VERSION=`0x504C4231`；读 mux 优先于视频寄存器及 SGDMA 通用 RAM。`DONE` 在 C2H 最后一拍进入应用 FIFO 后置位；`ERR=7` 保留且本接线不产生；`SESSION_ABORT` 锁存 `FAULT=1, ERR=6, DONE=0, READY=0`，须 SOFT_RESET 恢复。

## 离线验证

`run_sim.ps1` 已通过：PC2 控制模块测试、B 状态与安全复位测试、CDC READY/DONE 测试、半帧软复位测试，以及旧 RESET CDC 62 个向量。半帧用例确认 quiesce 被 DDR 域看见后才复位，随后有效 RESET 恰好返回一个 32B ack。

TD Release 2026.1 SP2，器件 PH1A90SEG324 speed 2；构建输出目录：`E:\KVmix\fpga_attention_ddr_planb_v1_r3_20261019`。

| 阶段 | 结果 / 文件 |
|---|---|
| 完整 RTL 综合 | 通过；`td_synth.log`、`attention_gate.db`；综合 WNS +0.498 ns |
| 完整布局布线、hold 修复、bitgen | 通过；`td_physical.log`、`attention_planb_full.db` |
| 最终时序 | `attention_planb_full.timing`：setup WNS +0.527 ns / TNS 0；hold WNS +0.020 ns / TNS 0；STA coverage 99.20% |
| 资源 | `attention_planb_full.area`：LUT6 22,171 / 64,320；slice 27,094 / 64,320；ERAM20K 98 / 272；DSP 4 / 240 |
| bit | `E:\KVmix\fpga_attention_ddr_planb_v1_r3_20261019\attention_planb_full.bit`；SHA256 `8701ADB00A259F95DAF8D77CEED7CB5CF500E3B8198676494768194330986EDE` |

时序余量尤其 hold 的 +0.020 ns 很小；`attention_planb_full_check.timing` 还列有厂商相机/PCIe 例程的 no-clock、未约束 I/O 等项目，不能把“报告 WNS 为正”解释为所有板上行为已证明。bit 生成不是 DDR 校准、BAR 读回或 Attention 数值的实测。

## 上板交接顺序

1. 由板卡操作者确认独占窗口和新 bit 路径/哈希后 JTAG 下载，记录 TD 成功日志；随后由 PC1 在 RK root 串口运行既定 `/usr/local/sbin/pcie1-recover.sh` 并留日志。B 不从本地替 PC1 执行 recovery。
2. PC2 先只读 BAR0 `0xAC`，必须为 `0x504C4231`；再只读 `0xA4` 状态和 `0xA8`（应为 0）。若 VERSION 不符，停在此处，不发 H2C。
3. 检查 READY、FAULT 和 FPGA DDR 初始化串口；初次校准未完成时 READY=0，本版没有初始 DDR 超时计时器。SOFT_RESET/SESSION_ABORT 控制测试通过后，再发 RESET_CACHE + OP_TEST；v41 从 seq **9300** 起，首错即停。不能在 RESET 前调用会停 C2H engine 的预 drain/`flush_queues()`。
4. BAR/OP_TEST 通过后再按现有数值 golden 对拍单层 ATTENTION，记录输入、响应、CRC、DDR/AXI 状态及延迟。patched driver 的 abort 为 best-effort，`deadline_enforced=false`。

PC2 已更正旧 C2H 超时的根因：runner 的预 drain 会停 C2H engine；去掉后 v40 的 OP_TEST 7400–7430 为 30/30。A956 尚未在修正后的 runner 上重测，不能据旧超时断言其 C2H RTL 损坏。新 Plan B bit 的实板状态仍待测试。

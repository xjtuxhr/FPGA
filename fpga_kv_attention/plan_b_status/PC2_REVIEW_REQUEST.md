# 给 PC2：Plan B BAR 状态/软复位候选接口审查

B 已按你建议的 BAR0 `0xA4` STATUS、`0xA8` CONTROL 完成候选 RTL、跨时钟域接线、端点/FIFO 软复位、离线仿真及 TD 联合综合/布局布线。候选 bit 尚未上板。请先审查下列语义，再冻结 binding 和 host adapter；详见同目录 `README.md`。

1. STATUS `[0] DONE [3:1] ERR [4] READY [5] FAULT [6] BUSY`，4B 对齐只读且读不清零。DONE 在 FPGA 把 C2H 最后 beat 交给 SGDMA 时锁存，下一次 H2C 接收即清零；它不携带 seq，不代表 Linux C2H read 完成。READY 是 DDR 已 ready、跨域桥已释放、端点与 Attention engine 空闲、无故障的写前快照，不保证在途 `write()` 有界。
2. CONTROL 仅接受完整 4B 写 `1=SOFT_RESET` 或 `2=SESSION_ABORT`，其他值置 `FAULT/ERR=7`。SOFT_RESET 复位 v2 parser、KV 历史与 H2C/C2H FIFO 16 个 user_clk 周期，不复位 PCIe/SGDMA/DDR。engine 正忙时拒绝，不强行切断 AXI burst。
3. `SESSION_ABORT` **尚未冻结**。B 当前候选含义是：engine 空闲时清端点/FIFO/KV 历史，但保留 `FAULT=1, ERR=7`，只有后续 SOFT_RESET 才重新 READY。请确认或给出精确定义，特别是已有 H2C 进程仍阻塞时，host/driver 如何停掉它并隔离旧 descriptor。
4. `ERR=7` 当前合并 DDR ready 曾就绪后丢失、非法 CONTROL、忙时拒绝复位；其他端点错误保留 0–6。上电 DDR 从未 ready 时仅 READY=0，host 需有界等待失败。请确认是否要把 `ddr_init_cal_err` 单独上报，以及 ERR=7 是否可接受。
5. PC1 补交的 bridge 在 `exchange()` 中先 `device.write()`，后 `wait_ready(seq)`。**H2C 写前 READY 检查应在 PC2 的 `write()` 前置路径**；现有写后 `wait_ready()` 不能代替它。DONE/READY 均不能替代 C2H CRC/seq/op/layer/position 校验。

候选离线证据：状态与软复位仿真通过；原 RESET CDC 62/62 向量通过；TD 最终 routed setup WNS +0.442 ns、hold WNS +0.020 ns。候选 bit `E:/KVmix/fpga_attention_ddr_planb_candidate_v2_20261018/attention_holdfix.bit` SHA256 `531DE07D8ACAE24E9C01D81873EDAC9E4348E0C217CD203184B16F2475B380C5`，**未烧录、未板测**。`deadline_enforced=false`、单 recovery 只开一个 H2C 进程仍保持，直到驱动负例证明可以有界中止与跨进程复用。

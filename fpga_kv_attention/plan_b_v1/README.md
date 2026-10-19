# Plan B v1：PC2 冻结接口的 Attention/DDR 集成

本目录基于 `functional_b64s3` (`MAX_T=64`, `SCORE_SHIFT=3`) 和先前 Plan B 候选工程，接入 PC2 的 `planb_status_ctrl.v`。PC2 交付包为 `E:/KVmix/planb_interface_20261019.zip`，SHA256 `AD5F7DAFA9F396A245BEB72D9A4EA3CBA2003ABE86AD35CD9B32B65D203F7D82`；原版控制模块 SHA256 `17059D842F14A9DE80B50BFDAC7D507F85511379FDE1FFFF8C50288FC0366019`。本目录的控制模块在原版基础上修复了“FAULT 已锁存时新 START 清掉 ERR”的问题，详见 diff。

PC2 后续总包 `FPGA_PC2_delivery_20261019(1).zip` 的 SHA256 为 `F7781F41481989EA11859A0C4CFB38D974F546B524145E61B8D0FB132FD9EB53`；其中冻结文档和控制模块与上面的本地子包逐文件 SHA256 一致。PC2 另报子包压缩文件 SHA256 `D086616B2CD86E0209C07186BD22276C01D8BEE83E44F7D6E31EEB269B7CBB71`，与本机压缩包哈希不同，不能把两个压缩包当作逐字节相同；接口源码本身已核对相同。

BAR0 user 节点使用逻辑偏移：`0xA4` STATUS、`0xA8` CONTROL、`0xAC` VERSION (`0x504C4231`)。顶层读 mux 对三个寄存器优先于相机寄存器和 SGDMA 通用 RAM。PC2 已在旧 bit 上观察到 `0xA8` 写后读回写入值；新版本的 `0xAC` 为上板身份检查点，读出该值之前不要开展 H2C 功能测试。`0xA8` 写入仍会别名到无语义的 SGDMA RAM[0x2A]，但读 mux 返回 0。

引擎连接：H2C 首拍握手产生 `start_i`；v2 响应最后一拍写入 C2H FIFO 后跨域产生 `done_i`；DDR 就绪、桥释放、端点空闲且无 FAULT 时才允许新帧首拍。首拍未获准时，H2C FIFO 的 `w_valid` 与 `tready` 一起门控，避免拒收的头拍偷偷入队；帧已开始后允许其余拍继续接收。端点旧错误码映射为 PC2 v1 的 1=SEQ、2=LAYER/POS、3=CRC/FORMAT、4=AXI/DDR、5=INTERNAL，DDR 已就绪后丢失映射为 4。

冻结语义：`ERR=7` 不由该接线产生，保留作内部错误处理；`SESSION_ABORT` 锁存 `FAULT=1, ERR=6, DONE=0, READY=0`，后续必须 SOFT_RESET。`DONE` 表示整个 C2H 响应已进入应用 FIFO，不表示 host 已读完。DDR 从未初始化成功时 READY 保持 0；本版无初次校准超时计时器，host 需有界等待并检查 FPGA 调试串口。

SOFT_RESET 和 SESSION_ABORT 脉冲先进入 `planb_reset_guard`。它关闭 H2C 首拍入口，经双向同步让 DDR 时钟域确认停止启动新的 Attention，再等待已接受的 AXI 事务结束且安全状态连续稳定 5 个 `user_clk` 采样，才拉住应用复位 16 周期；C2H/H2C FIFO、parser 和 KV 历史随之清空。半途停止发送的 H2C 帧因此也能清掉，不依赖 parser 自行回到 idle。已接受但未完成的 AXI burst 由 CDC 侧 AW/B、AR/RLAST 计数保护，不能被软复位截断。若 AXI 在超时后仍欠响应，软复位可能一直等待，host 的有界轮询应失败并转硬件恢复；**本 RTL 不保证内核阻塞 `write()` 的硬取消，也不能据此把 `deadline_enforced` 改为 true**。SESSION_ABORT 清应用队列后保留 `FAULT=1, ERR=6`，须再 SOFT_RESET。

离线检查：PC2 原控制模块 testbench、B 的读 mux/故障锁存/安全复位测试、CDC 首拍门控与 DONE 测试、半帧软复位恢复，以及 RESET CDC 62 个向量全部通过。运行 `run_sim.ps1` 可重放。新的完整 TD 联合综合、P&R、bitgen 和实板验证需分别记录；旧 A956 bit 的综合或烧录记录不能替代。

构建新工程（不触碰原 TD 工程，也不烧录）：

```powershell
& 'C:/Users/47736/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' fpga_kv_attention/plan_b_v1/assemble.py --out E:/KVmix/fpga_attention_ddr_planb_v1_r3_20261019
& 'C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe' E:/KVmix/fpga_attention_ddr_planb_v1_r3_20261019/synth_functional.tcl
& 'C:/Anlogic/TD_Release_2026.1_SP2.200.067/bin/td_commands_prompt.exe' E:/KVmix/fpga_attention_ddr_planb_v1_r3_20261019/physical_clean.tcl
```

板测须另约独占窗口。新 bit 经 JTAG 下载后，由 PC1 在 RK root 串口执行 `/usr/local/sbin/pcie1-recover.sh`；PC2 先只读 `0xAC`、`0xA4`、`0xA8`，再在一个 H2C 进程内测试 RESET/OP_TEST。每次新的 H2C 进程前按现行规则恢复 PCIe，直到“跨进程无需恢复”负例实测通过。

PC2 已纠正此前的 C2H 超时归因：旧 runner 在 RESET 前的 `flush_queues()` 会 drain/stop C2H engine；去掉预 drain 后 v40 的 7400–7430 OP_TEST 30/30 通过。A956 尚未用修正后的 runner 复测，不能据旧超时断言其 C2H RTL 损坏。PC2 的 v41 还修复了高文件描述符的 `select()` 问题，下一组 seq 从 **9300** 起；patched driver + AbortableDevice 的阻塞写取消仍是 best-effort，`deadline_enforced=false`。

# 方案 B：H2C 超时与 SGDMA 恢复的团队分工（2026-10-18）

**团队决定：采用方案 B。** 本文更新[10-18 进度快照](TEAM_PROGRESS_AND_NEXT_STEPS_20261018.md)和 PC2 的《H2C 超时与恢复门槛》里“方案待选择、短期先用 A”的建议；旧文档仍保留当时的实测事实。方案 B 要同时解决两件事：阻塞 H2C 写不能被 host 的短 deadline 中断，以及一个恢复窗口内 SGDMA engine 跨进程不可复用。**不以方案 A 的显式风险接受标志放行 v40 NPU→FPGA 实板测试。**

## 已证事实与本阶段边界

- PC2 实板请求 0.5 s deadline，阻塞 H2C 写约 9.998 s 才返回；随后新进程可能在 RESET 上阻塞并报 `Errno 512`。当前能力仍为 `deadline_enforced=false`、`session_reusable=false`。Python 外层计时和写前轮询都不能独立证明硬 deadline。
- 当前 B64S3 功能 bit 的 RESET/TEST、CPU/HF v5 单层 Attention、不同 K/V 的 30 层隔离及非空缓存 RESET 已有实板证据，但**没有 host 可读的应用 READY/FAULT/DONE 寄存器**。UART 状态不是 PCIe host 状态接口；旧摄像头 BAR 版本字不能冒充新接口。
- PC1 已补 v40 实际 RK/NPU Q/K/V 捕获的完整 `summary` 和运行日志；B 已完成 8 个位置的离线 wire/reference 复核。PC1 文件明确 `fpga_executed=false`、`pcie_executed=false`。本批 NPU 输入仍无 FPGA 回包。
- B 功能版源码和 TD 构建输入已固定在 [`codex/fpga-kv-attention@9cb9b3f`](../fpga_kv_attention/functional_b64s3/README.md)，参考 bit SHA256 为 `C510C4FBA08D76B82FC5B1773BF460E60E920F12488627FF4BC64D09A9FAB378`。方案 B 会产生**新 RTL/驱动/bit 版本**，不得用旧 hash 代表新实板结果。

## 接口先冻结：PC2 + B，PC1 审核调用语义

在修改现有功能工程前，PC2 和 B 先共同交付一页可执行的状态接口表，PC1 审核它能否满足模型调度。至少写清以下项目；**BAR 编号、偏移、寄存器值当前未定，不能按旧摄像头例程猜测**：

| 项目 | 必须明确的内容 | 主责 |
|---|---|---|
| 寄存器可达性 | FPGA 状态经哪个 PCIe BAR/桥接通道暴露；Linux 哪个设备节点、逻辑偏移和地址公式；只读或读清零副作用；32-bit 读写方式 | PC2 查驱动/桥接，B 核对 RTL 接线 |
| READY | 表示哪一层已就绪：PCIe 链路、DDR 校准、endpoint 接收 FIFO、或当前请求可接收；读到 READY 后何时可能撤销 | B 定义并实现，PC2 审核 host 用法 |
| FAULT | DDR init/ready 丢失、AXI/Attention、协议错误、SGDMA 故障如何区分；是否锁存、如何清除、是否要求重建会话 | B 定义 FPGA 错误，PC2 定义传输错误 |
| DONE/请求身份 | DMA 完成、FPGA Attention 完成和 C2H 完整帧的区别；如何防止旧 DONE/旧帧满足新 seq；RESET/清状态的时机 | B + PC2，PC1 审核 seq/层/位置语义 |
| 复位与时钟域 | PCIe/DDR 两域同步、上电与重新配置默认值、DDR 未 ready 时行为、状态更新的原子性 | B 实现，PC2 验证 host 观测 |

状态表要配一份最小 mock/RTL 向量：上电未就绪、变 READY、正常请求完成、运行中失去 DDR ready、坏帧/AXI 错误、RESET 后新会话。先对齐接口再并行写代码，避免 B 做出的寄存器 PC2 实际读不到。

## 分工与可并行工作

| 成员 | 现在负责 | 可审查交付物 |
|---|---|---|
| **B：FPGA** | 从已冻结的 B64S3 工程副本增加 host 可读状态通路；把 `READY/FAULT/DONE` 与实际 DDR 校准、endpoint、Attention/AXI 状态相连；处理跨时钟域和旧状态清除。保留 v2 帧/RESET/KV 历史语义。先仿真，再 TD 联合综合、布局布线、时序与 bit 生成。 | 状态接口 RTL/仿真、BAR 接线证据、TD 日志、资源/时序、新 bit SHA256、JTAG 烧录记录；旧 bit 保留以便回退。不得只输出常量 READY。 |
| **PC2：PCIe/驱动** | 核对 user/control 节点到状态寄存器的真实地址；实现并测试 host 读状态、轮询和 FAULT 处理。同时审查 SGDMA 驱动/engine 生命周期，设计可验证的 open/close 重初始化或可中止 DMA 路径，解决第二个进程 `Errno 512`。 | 寄存器映射与绑定版本、adapter/驱动提交、部署文件哈希、有限等待与中止语义、连续独立进程测试、故障注入日志。驱动完成中断不得被应用轮询替代或关闭。 |
| **PC1：RK/NPU/模型 host** | 审核状态表和 PC2 真实 capability；把状态检查接入正式 NPU→FPGA bridge，明确帧/seq 的唯一负责人。继续用 v40 自身参考拆分 NPU、FP16、Attention、O/层输出误差并确定验收阈值。 | host/bridge commit、最终 summary/stdout、能力门控测试、真实 FPGA C2H 接回 O projection 的单层记录；不以旧 Python 属性 True 绕过门槛。 |

PC 上的 RTL 仿真、驱动源码审查、mock 和数值分析可并行。板卡/驱动/bit 实验按[协作规则](../pcie_contract/COOPERATION.md)使用独占窗口；B、PC2 和 PC1 不在同一时段分别操作这台 RK3576+FPGA 板。

## 顺序与放行条件

1. **接口冻结（PC2+B，PC1 签核调用语义）。** 状态寄存器真实可达路径、位定义、清除/复位、错误优先级和版本号写入接口文档；host mock 与 RTL 状态向量一致。当前 bit 无此接口，不直接开始 v40 实板 session。
2. **离线实现（并行）。** B 在工程副本实现状态通路及负例 testbench；PC2 实现 adapter/驱动生命周期修复及有限等待；PC1 接正式 bridge 和数值门槛。不能仅把配置里的 `deadline_enforced` 改为 true。
3. **新 bit 与驱动分别验证。** B 的 TD 综合/P&R 报告确认 Attention/DDR 仍保留且时序满足；PC2 在实际绑定上读出各状态，验证上电未就绪、就绪、故障和复位，不把固定寄存器值当成功。
4. **阻塞与复用负例。** PC2 用受控故障证明：写前不 READY 能快速拒绝；写入开始后遇到阻塞也能在约定的有限时间内返回并安全中止/隔离；连续两个及以上独立 H2C 进程无需 PCIe recovery 仍可各自完成 RESET/TEST。记录 monotonic 实测时间、内核日志、驱动/bit hash 和故障后的 KV/会话状态。**READY 预读只能覆盖写前状态，不能替代在途写的中止试验。**
5. **新 bit 回归。** B+PC2 重跑 RESET + 30 TEST、CPU/HF v5 的 8 次 Attention、不同 K/V 的 30 层隔离及非空缓存 RESET，逐项核对原始帧/CRC/seq/输出，并检查旧状态不会误报 DONE。新 bit 的结果单独归档，不借用旧 bit 的通过记录。
6. **能力放行后才做 v40 单层。** PC1 审核第 4、5 步证据与实际部署版本，PC2 再在独占窗口运行本批 `RESET + 30 TEST + 8 ATTENTION`。交付 39 对真实 H2C/C2H 帧、当前 seq、bit/driver/adapter/binding/host hash。B 对 v40 wire 与定点 golden 逐位复核；PC1 将真实 C2H 接回 O projection/层输出。
7. **后续扩展。** 单层实际调用链通过后，先真实 30 层 B 和质量/性能，再接 U/M 的量化 DDR、metadata 和 RPC tail。方案 B 的负例与跨进程恢复证据不足时，不把 `deadline_enforced` 或 `session_reusable` 标为 true，也不外推吞吐/稳定性。

“有限时间”阈值、故障注入方式和驱动取消后的恢复状态须在第 4 步**之前**由 PC1/PC2/B 写入测试计划；仅有正常成功案例不能证明硬 deadline。发生超时、CRC/seq 不符或状态不可信时停止会话，保存原始证据；不自动重发可能追加 KV 的请求，也不用 CPU/mock Attention 冒充 FPGA 输出。

## 版本与证据入口

- PC2 原问题与方案比较：`E:\KVmix\fpga\docs\PC2_H2C_TIMEOUT_AND_RECOVERY_DECISION_20261016(1).md`，SHA256 `B6BE7AC93B0B483AAA16F99CE637830CCF6A404CFD1C28FC8FF845B1F48AB705`。其“方案待选择、A 先行”和“尚无 NPU capture”是**历史描述**；本文件记录团队新决定，PC1 的 v40 capture 已到。
- PC1 捕获补充：`E:\KVmix\summary(1).json` 与 `E:\KVmix\run(1).log`；状态 `PASS_REAL_NPU_QKV_CAPTURE_V40`，8 个位置、24 次 NPU 调用，`fpga_executed=false`、`pcie_executed=false`。离线审查见 [NPU v40 复核](NPU_V40_CAPTURE_REVIEW_20261018.md)。
- 旧 B 功能 bit/工程见[功能版源码交付](../fpga_kv_attention/functional_b64s3/README.md)；新方案 B 的 bit、驱动和 host 提交号尚未产生。PC1 负责审核各分支 PR 后集成 main；本文不把分支提交视作已部署。

本文是团队执行计划，不代表方案 B 已实现或已通过实板验收。开放问题继续在 [UNKNOWNS](UNKNOWNS.md) 维护。

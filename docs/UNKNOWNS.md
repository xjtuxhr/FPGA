# UNKNOWN Registry（唯一开放问题清单）

更新：2026-09-23。`D1` 是 [PLAN](../PLAN.md) 发布后首次全员开工日，不是今天的日历日期。到期意味着必须得到证据或在该里程碑触发止损/调整，不能靠猜测把 UNKNOWN 改为已确认。`PROJECT_STATUS.md` 只记录进度并链接本清单，不维护第二份独立 UNKNOWN 表。

| ID | UNKNOWN | 为什么重要 | 如何确认、保留什么证据 | 阻塞阶段 | 最晚解决 |
|---|---|---|---|---|---|
| MODEL-001 | 正式 stories15M checkpoint 的 revision/hash | 决定所有 golden 与复现 | 固定下载来源和 SHA-256；记录 C header、Python config | 软件 reference | D3 |
| MODEL-002 | 实际 checkpoint 是否 shared classifier/weight tying | 影响唯一权重副本与容量估算 | 读取实际 `.bin` header 的共享标志，对照 embedding/head 张量 | W8 导出/装载 | D3 |
| MODEL-003 | tokenizer 文件 revision/hash | token ID 错位会使整机结果无意义 | 固定 `tokenizer.bin` 哈希，做 encode/decode golden | 软件 reference | D3 |
| MODEL-004 | BOS/EOS、生成停止及空 prompt 规则 | 决定 prompt/生成对拍 | 用固定 checkpoint/tokenizer 跑作者参考程序并记录 ID 序列 | 软件生成/演示 | D7 |
| NUM-001 | activation dtype 与每层范围 | 决定 DSP 映射和误差 | 软件定点模拟，逐层范围/误差表 | GEMV/单层 | D14 |
| NUM-002 | accumulator 位宽及溢出策略 | 长度 768 的 W8×A16 可能超过 32-bit | 最坏范围证明 + 定点 golden + DSP 综合 | GEMV/单层 | D14 |
| NUM-003 | GEMV 每 row/组的 scale、输出格式与舍入 | 决定层间接口 | 固定 W8 导出格式，逐层误差与饱和统计 | GEMV/单层 | D14 |
| NUM-004 | RMSNorm 平方和、倒平方根中间精度 | 误差会跨 6 层累积 | 固定点 reference，边界向量、逐层对拍 | 单层 B | D14 |
| NUM-005 | RoPE sin/cos 和旋转结果精度 | QK 误差与位置相关 | 0–255 位置的 reference、ROM/近似误差 | 单层 B | D14 |
| NUM-006 | softmax 指数、求和、倒数格式与近似 | 稳定性、概率和及极值风险 | 极值 score、不同 T 的定点 golden | 单层 B | D14 |
| NUM-007 | SiLU 近似区间、表/段数与中间位宽 | FFN 质量和资源 | 输入范围统计、函数误差与 block 对拍 | 单层 B | D14 |
| NUM-008 | logits 输出 dtype/scale | 影响 top-1、32k buffer 与 PCIe 字节数 | 与参考 logits、top-1、采样结果对拍 | 完整 B | D21 |
| NUM-009 | B 的 FP16 KV 转为共同 Attention 定点格式的规则 | 保证 B/U/M 只改变存储表示 | K/V 边界值转换与 QK/PV 对拍 | 单层 B | D21 |
| GEMV-001 | W8×候选 activation 在 PH1A90 上的 DSP 实际映射 | 240 DSP 不能直接换算 lane | TD 综合小整数 GEMV，保留资源/时序报告 | GEMV 扩展 | D14 |
| GEMV-002 | MAC lane 数 | 受带宽、频率、DSP 与 bank 限制 | 8/16/24/32 候选 sweep；记录有效吞吐/资源 | 完整 B 性能 | D21 |
| GEMV-003 | weight tile 行数/字节数 | 决定 ERAM 用量与 DDR burst 效率 | 参数 sweep + 实际 buffer 综合报告 | 单层 B | D14 |
| GEMV-004 | ERAM banking、端口和同周期读取能力 | 多 lane 可能被读口卡住 | ERAM 手册 + 综合小例程 + 冲突测试 | 单层 B | D14 |
| GEMV-005 | DDR 权重存储与 ERAM tile 内部 layout | row-major DDR 不直接给出跨 row 同列的 P 个权重 | DDR burst → tile banking/transpose 小实验 | 单层 B | D14 |
| GEMV-006 | 双缓冲是否能真实 overlap | 影响是否值得占用两倍 ERAM | 对比单/双 buffer 的 DDR wait 和周期 | 性能优化 | D36；可延后 |
| DDR-001 | 当前板级 DDR IP 版本、校准信号、用户接口 | 所有大权重/完整 KV 的前提 | 官方板级工程与读写日志 | G1/全模型 | D7 |
| DDR-002 | 用户接口宽度、burst、时钟和地址对齐 | 决定 tile 格式与吞吐 | IP 文档、例程、连续突发测试 | G1/GEMV | D7 |
| DDR-003 | 板上有效顺序读取带宽及 stall | 决定可持续 GEMV lane 数 | 实测多长度连续读，记录时钟/字节/周期 | GEMV 架构选择 | D7 |
| DDR-004 | 读写并发、仲裁和最坏等待 | 权重读与 KV 写可能互相阻塞 | 混合读写压力测试 | 单层 B | D14 |
| DDR-005 | 预取下一 tile 与当前 MAC 是否并行 | 决定双缓冲实际收益 | 端口/仲裁审查 + 周期对比 | 性能优化 | D36；可延后 |
| KV-001 | M recent FP16 长度与动态峰值 | 容量、迁移和质量均依赖它 | 软件 B/U/M sweep，固定策略 JSON 与 peak bytes | U/M 实现 | D29 前 |
| KV-002 | K 沿 token、V 沿 channel 的分组轴是否最终采用 | 决定访存遍历与分组量化 | 对照 KVmix 算法、定点 reference 和 tile 读取实验 | U/M 实现 | D29 前 |
| KV-003 | K/V group size，K3 特殊打包规则 | 决定 payload、元数据与误差 | 软件量化评测、打包/解包 golden | U/M 实现 | D29 前 |
| KV-004 | 每组 scale/min 或 zero-point 的数值格式 | 预算脚本目前假设 4 B/组 | 软件 reference + 地址布局文档 | U/M 实现 | D29 前 |
| KV-005 | 量化 metadata 的存放/对齐/索引 | 容量预算不等于真实 DDR 流量 | 固定地址图、读写单测 | U/M 实现 | D29 前 |
| KV-006 | token 离开 M 的 FP16 tail 时如何量化迁移 | 可能产生重排和写放大 | 迁移状态机方案与逐 token golden | M 模式 | D29 前 |
| KV-007 | 哪些层是 M 的重要层、数量与离线策略版本 | 当前脚本“2 层”只是容量快照 | 离线重要性分析 + 与随机分配比较 | M 模式 | D29 前 |
| KV-008 | U 的 K 时间轴分组未满时如何维持全 token K2 | 不得偷用 FP16 tail；部分组增长可能反复重打包/重算 scale | 单 token 起逐步追加到组满的量化/反量化 golden 与写字节统计 | U 模式 | D29 前 |
| HOST-001 | RK3576↔FPGA 官方工程、driver 与实际板卡版本是否匹配 | 无法加载正式权重和读状态 | 枚举/驱动/小数据读写日志 | 权重装载闭环 | D7 |
| HOST-002 | PCIe 到 FPGA DDR 的真实可用写入路径 | 现有视频示例不等于权重装载器 | 小数据 DMA→DDR→校验闭环 | 15M 全模型 | D7 |
| HOST-003 | token 命令、logits/status 地址与 runtime packet | host 与 FPGA 需同一协议 | 寄存器表、模拟/板上往返测试 | 完整 B | D21 |

## 已解决的定义冲突（不再列为 UNKNOWN）

**KV-000，RESOLVED：U 无 recent FP16 tail。** [PLAN](../PLAN.md) 的冻结定义为 B=FP16 KV 存储，U=所有层/所有 token K2/V2，M=分层 K2/3、V2/4 并带近期 FP16。2026-09-23 已修正 [预算工具](../tools/budget_check.py) 的 U 路径与 self-test。M 的 tail **长度**、分组和 metadata 仍在上表开放；当前预算数字只是显式假设。

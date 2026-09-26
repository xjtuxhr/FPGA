# UNKNOWN Registry：唯一活动清单

更新：2026-09-26。方案C、正式Smol135M、stories15M参考定位已解决，不再列UNKNOWN。期限为原50天D序号，不重置；已越过门槛应立即补证据。架构冻结不表示实现可行性已验证。

| ID | UNKNOWN / 为什么重要 | 如何确认 | 阻塞阶段 | 最晚冻结 |
|---|---|---|---|---|
| HW-001 | 实物SEG324、板版/BOM、4GB RK内存/256MiB FPGA DDR、K单位与约束是否匹配 | 丝印/BOM/原理图、TD器件、RK内存信息交叉核对；FAE确认 | 基础bring-up | D7 |
| DDR-001 | FPGA DDR controller用户宽度、burst、实际速率 | 匹配官方例程/IP设置，读写校验与接口日志 | KV DDR路径 | D7 |
| DDR-002 | KV读写并发、有效带宽、GQA复用/多遍与迁移流量 | 分离读写/混合/真实KV tile benchmark，不用引脚速率代替 | Attention性能 | D21 |
| NPU-001 | Smol QKV/O/MLP/LM Head实际MatMul shape与格式支持，尤其[49152,576] | 匹配RK3576 SDK/runtime，逐shape编译/运行/对拍，测试head分块 | RK linear可用性 | D14 |
| NPU-002 | batch1/M=1真实latency、利用率、权重常驻与内存峰值 | 预热后逐shape计时，记录权重加载/常驻、副本/OS/workspace | 完整系统速度/容量 | D14 |
| NPU-003 | CPU↔NPU copy/layout/cache/sync与可分层调度 | 分测prepare/run/wait/read，核对RKNN分图/MatMul能力；RKLLM整模型输出不能代替外部Attention | RK/FPGA集成 | D14 |
| PCIE-001 | 实际板内链路/SGDMA驱动是否可用，候选小包往返latency | 匹配工程双向buffer校验，1920B H2C+1152B C2H含通知/等待计时 | tensor接口 | 链路D7，延迟D14 |
| PCIE-002 | 30层串行请求响应累计开销 | 依赖链benchmark，区分transfer与sync；不能只测大块带宽 | 整机速度 | D14 |
| PCIE-003 | packet/地址/layout/完成标识、层号/位置/序列状态、一致性/错误处理 | 在小包证据基础上写接口spec，与golden联合评审；本轮不冻结packet | 正式host与RTL集成 | D21 |
| MODEL-001 | 正式checkpoint/tokenizer/量化制品hash与PC评测版本一致性 | 签核现有本地hash+转换配置/版本+PC日志manifest，模型ID已冻结不重选 | 质量可复现 | D14 |
| MODEL-003 | tokenizer部署文件集合、encode/decode一致性 | 本地tokenizer.json/config/vocab/merges/special tokens，PC/RK相同测试集对拍 | 文本demo | D28 |
| MODEL-004 | BOS/EOS=0实际添加/停止规则 | 检查tokenizer配置，prompt→ID/停止测试 | generation/PPL | D28 |
| NUM-001 | RK/NPU算术量化格式、QKV/output PCIe dtype/scale/layout | CPU reference与实际RK输出对拍，固定B/U/M同配置 | 数值边界 | D14 |
| NUM-002 | FPGA QK/PV input、accumulator宽度、scale/溢出/舍入与输出格式 | 最坏范围分析+golden+原语综合，不直接冻结A8/A16 | Attention datapath | D14 |
| NUM-003 | softmax score/exp/归约/倒数精度与近似 | 极值/长短context稳定性对拍，端到端质量回归 | Attention准确性 | D21 |
| NUM-004 | norm/RoPE/SiLU具体CPU/NPU归属及数值一致性 | RK算子支持/latency+Smol HF配对reference，避免错误重排 | block/model集成 | D21 |
| NUM-009 | FP16 KV存储到共享Attention数值格式的转换 | 特殊值/范围、误差及resource/latency测试；B不是整模型FP16 datapath | B/U/M公平性 | D21 |
| RTL-001 | Attention-only真实ERAM/IP/FIFO资源，能否不用disRAM | TD每阶段资源/推断RAM模式与端口报告；204KiB只是候选 | 资源验收 | 初证据D21，最终D35 |
| RTL-002 | Attention lane/DSP映射、banking/tile、overlap与timing | 微核sweep/综合/P&R/DDR实测；不套全模型GEMV lane | 性能验收 | D21 |
| KV-001 | M recent长度与重要K/V层ID/比例 | PC profiler与tail-only/同字节随机消融；默认32/3不是冻结 | U/M质量与容量 | D29 |
| KV-002 | K/V group轴/size、scale/min格式、K3 dense或cuda11、metadata布局 | 精确量化reference+layout例子+容量/对拍，和PC设置比对 | quant/dequant接口 | D29 |
| KV-003 | FP16 tail驱逐、旧K不完整组、迁移/追加重算策略 | 跨组边界逐tokengolden、DDR读写计数、原子更新/复位测试 | M/U Cache正确性 | D29 |
| KV-008 | cache reset、因果mask、position、prefill/decode与GQA头映射 | 单层/序列golden，跨请求状态测试 | B完整模型 | D28 |
| EVAL-001 | PC报告完整配置/源码/commit、tail/context是否一致 | 获取团队脚本/日志，固定样本与评测规则 | 实验公平/复现 | D29 |
| EVAL-002 | 新NPU+FPGA数值路径质量与性能目标/收益 | B先评PPL/token，再U/M与RK-only同质量对照；分阶段计时 | 最终验收 | B D28，指标D35，报告D42 |

## 已解决或退出当前阻塞的旧问题

- ARCH：方案C/正式Smol135M已冻结；不再“等待40–80M主模型”。
- MODEL-002：本地Smol header/config已证实tied embedding；正式制品一致性仍属MODEL-001。
- KV-000：U无recent tail已冻结，脚本self-test保护。
- 旧GEMV-001～006（FPGA全模型DSP/lane/权重tile/layout）、NUM-008（FPGA logits）、RES-001（640+64KiB）、HOST-002（完整权重装载FPGA DDR）不再阻塞主线；相应历史分析见 [旧架构](COMPUTE_ARCHITECTURE_FULL_FPGA_HISTORY.md) 和 [REVIEW](REVIEW.md)。
- 原GEMV GQA复用问题改归DDR-002/KV-008，HOST运行时问题归PCIE-001～003；不把问题改名当作已经解决。

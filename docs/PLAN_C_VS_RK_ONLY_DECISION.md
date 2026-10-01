# 决策备忘：方案 C vs RK-only 收支平衡

**状态**：待数据裁决 | **关联**：UNKNOWNS NPU-002、PCIE-001/002、EVAL-002、RTL-001 | **裁决时限**：D14 前出初步结论

## 1. 问题

方案 C 的 FPGA 收益（非均匀量化 KV 算术、attention 卸载）在 135M / T≤256 / batch=1 下理论收益极薄（FPGA 仅 8.8M MAC/token，KV 仅 1.67 MiB），而代价是每 token 30 次 PCIe 串行往返。存在"净速度不如 RK-only"的结构性风险，文档已承认"短T/batch1 可能被通信抵消"。

## 2. 待测指标（D14 前必须集齐）

| # | 指标 | 来源 | 测法 |
|---|---|---|---|
| 1 | RK-only 完整模型单 token 延迟 | NPU-002 | RKLLM 整模型（或逐 shape 拼接）M=1，预热后计时，记录权重常驻/内存峰值 |
| 2 | RK 侧分 shape 投影延迟（QKV/O/MLP/LM Head，尤其 49152×576） | NPU-001 | 逐 shape 编译/运行/对拍，测 head 分块 |
| 3 | 单次 PCIe 小包往返延迟 | PCIE-001 | 1920B H2C + 1152B C2H，含通知/等待，双向 buffer 校验 |
| 4 | 30 层依赖链累计开销 | PCIE-002 | 依赖链 benchmark，**分开计 transfer / sync / compute**，禁止重复计重叠时间 |
| 5 | FPGA 单层 attention 耗时（T256） | RTL-001 初证据 | Attention-only runtime + DDR 本层 KV 扫描实测 |

## 3. 收支平衡公式

```
方案C估算/token = 30 × (单次往返延迟 + FPGA单层attention) + RK全部投影时间
RK-only基线/token = 指标1 实测值

方案C净收益 = 基线 − 方案C估算
```

## 4. 判断阈值

| 结果 | 判定 | 动作 |
|---|---|---|
| 方案C估算 < 基线 | 通过 | 按原计划推进，D14 冻结小包接口 |
| 方案C估算 > 基线，差距 ≤ 20% | 风险区 | 先做往返优化（轮询替代中断、描述符环、门铃合并、FPGA 内 transfer/compute overlap），再复测一次 |
| 方案C估算 > 基线 2× 以上 | 不划算 | 启动方案 C 冻结决策重审，走 EVAL-002 同质量对照作为证据 |

**附加裁决维度**（速度打平时仍可能保住方案 C）：
- T2048 / batch>1 场景下往返被摊薄、attention MAC 涨到 RK 线性的 50%+，重新代入公式
- 项目目标本身是否包含"异构加速演示"（若赛事/课题要求 FPGA 参与，纯速度不是唯一判据）

## 5. 两种结果下的应对

**结果 A：往返延迟足够低 → 继续方案 C**
- 锁定 30 次往返为常设约束，进入 FPGA Attention-only 综合、PCIE-003 接口 spec
- 后续每阶段（B→U→M）都用 RK-only 同配置复评，防止中途劣化

**结果 B：打不过 RK-only → 三档降级选项**
1. **优化往返**（第 4 节风险区动作），大概率能压缩 2~10 倍——先别放弃
2. **重定义 FPGA 角色**：不做 attention，只做 KV Cache 卸载/量化存储（RK 侧做 attention，读回 FPGA 的 KV）——往返仍在，但 FPGA 价值点变成"省 RK 内存带宽"，需重算
3. **正式重审冻结决策**：团队 FROZEN 决定须走明确流程，以 NPU-002/PCIE-001 实测 + EVAL-002 对照为证据，不能凭"感觉 FPGA 更强"继续

## 6. 时间锚点

- D7：PCIE-001 链路可用的初证据（HW-001、DDR-001 同步过门槛）
- **D14：本备忘裁决日**——指标 1/3/5 集齐，出"继续/降级/重审"三选一
- D21：FPGA attention-only 资源/性能证据（RTL-001/002），若此前已判降级则本节点验证据
- D35：EVAL-002 指标验收；D42 最终报告

## 7. 数据纪律

- 所有对照必须**同 NPU 权重、同 B 模式、同 generation 配置**（COMPUTE_ARCHITECTURE.md 第 67 行）
- 分测 CPU、NPU、conversion、PCIe transfer/sync、FPGA attention，端到端合并时禁止重复计重叠时间
- 往返延迟记录分位数（P50/P99），不用单次最小值宣称
- 结论写入前把原始日志归档，防止"数字只存在于聊天记录"

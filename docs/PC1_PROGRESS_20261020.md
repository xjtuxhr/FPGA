# PC1 当前进度：v44 B 实板结果与质量问题分级

更新：2026-10-20（PC 接收日期）。本文供 PC2 和 FPGA 队友快速了解 **RK3576 host/NPU 侧**的实测边界；开放问题仍以 [UNKNOWNS](UNKNOWNS.md) 为唯一清单，协议仍以 [PCIe v2 契约](../pcie_contract/README.md) 为准。板端日志路径中的 2026-04-27 是未校准的板上时钟，不是本文日期。

## 一句话状态

PC1 已在新 Plan B bit 的操作者声明下，通过真实 RK3576 NPU ↔ PCIe ↔ FPGA **B（FP16 KV 存储）Attention** 串行链完成两条英文 prompt、共 21 个前向位置、各生成 8 个 token。两组生成 ID 与现有 PC W8/A8 候选完全相同；逐位置 logits 比较为 **20/21 个 top-1 一致，但不是浮点数值一致**。这是短文本功能与候选比较，不是 HF 一致性、正式 PPL、长上下文、吞吐量或 U/M 验收。

## 已取得的实板结果

| 阶段 | 本次能证明什么 | 不能外推成什么 |
|---|---|---|
| v40 | 第 0 层连续 8 位置，真实 NPU QKV → FPGA B Attention → NPU O/MLP 局部通过；1 RESET、8 ATTENTION、56 NPU MatMul | 30 层生成、质量、U/M |
| v41 | 30 层、单个固定 token 前向局部通过；`V41_FULL_B_PASS`、seq 9300–9330、argmax 727 | 多位置生成、逐层 HF parity |
| v43 | 英文 `Once upon a time`（4 个 prompt ID），5 个前向位置生成 ID `[28,665]`，解码 `, there`；`V43_REAL_TEXT_PASS`、exit 0、最后 seq 9550 | 正式质量、PPL、长序列、速度或故障恢复 |
| v44 | 两条真实英文 prompt，21 个前向位置，630 次真实 FPGA Attention、4431 次 NPU linear、2 次请求 RESET；另有独立 B 向量探针 RESET+ATTENTION，共 634 帧；exit 0、最后 seq 11133 | HF parity、数据集 PPL、U/M、生产速度或长上下文 |

### v44 已取回的逐位置数值证据

操作者运行目录：`/home/kvdev/work_pc1_npu/full-text-v44-planb.q4RMWe/host/results/v44_b_expansion_20260427T204634_7515/`。PC1 已取回其中 `summary.json` 和全部 21 份 F32 logits；原包 SHA256 为 `20C9A4B40D0B761154E950880560290584CBB37807EE290776C6FB4605032E97`。离线分析逐一验证 logits 字节数及其 `summary.json` SHA256，仅对**输入 token 前缀相同**的位置和既有 v38 PC 候选比较；本次两个前缀全部相同，因此 21/21 均可比较。后者使用 CPU F32 Attention，不是 HF float，也不是 FPGA 定点 Attention 的逐 bit oracle。

| 请求 | 前向位置 | 生成 ID 是否与 PC 候选相同 | top-1 与候选相同 | 全词表最大绝对 logits 差 | 目标 token 平均 NLL（板 / 候选） |
|---|---:|---|---:|---:|---:|
| `Once upon a time` | 11 | 是：`[28,665,436,253,7436,1838,8180,3365]` | 11/11 | 6.5310 | 1.4548 / 1.3216 |
| `The little girl` | 10 | 是：`[436,253,1838,8180,30,198,8113,436]` | 9/10 | 5.4262 | 3.0751 / 2.7236 |

唯一 top-1 分歧发生在第二条 prompt 的 position 0：板端 ID `31883`，候选 ID `15279`；这不是生成时选择 token 的位置，因此不与两条最终生成 ID 一致相矛盾。两条请求均由 `MAX_NEW_TOKENS` 停止，没有 EOS 证据。v44 的成功摘要还报告 `real_npu=true`、`real_fpga_attention=true`、无 CPU fallback、211 常驻 context、FD 采样 3→1272→4；后者单次残留差 1 **不证明泄漏**。`deadline_enforced=false`，H2C 写仍没有被 Python timeout 强制中止。下一次全局 seq 必须 **大于 11133**，新请求仍须显式 RESET。

本次探针用保存的 B 输入先发送 RESET seq10500，再发送 layer0/position0 Attention seq10501；返回与已保存的 1152B 定点向量逐字节一致。v44 记录的 bit SHA256 `a9560e762c5c2dbf89cb4c10346ca8c2a849fb2da7cfe4d4df7f93a4a5ab2887` 是**操作者声明与包的限定条件**，不是已从配置后的 FPGA 读回的哈希。板上剩余 `wire/`、checkpoint 和原始 bit 下载记录未随本次便携包取回；不要宣称其内容已独立审核。

v43 成功分支要求一次 `RESET_CACHE`、150 次真实 `ATTENTION`（30 层 × 5 位置）、211 个常驻 NPU linear context 各调用 5 次，共 1055 次 NPU linear；无 CPU linear/Attention fallback。前两个生成 ID 与既有 PC 软件候选相同，仅说明**这个短样本**一致。操作者提供的关键回显：

```text
WORKDIR=/home/kvdev/work_pc1_npu/full-text-v43.4cYRWV
EVIDENCE=/home/kvdev/work_pc1_npu/full-text-v43.4cYRWV/host/results/v43_real_text_20260427T200426_3791
SEQ_RESERVED=9400..9550
{"event": "V43_TOKEN", "token_id": 28, "generated_ids": [28], "decoded_cumulative": ","}
{"event": "V43_TOKEN", "token_id": 665, "generated_ids": [28, 665], "decoded_cumulative": ", there"}
{"event": "V43_REAL_TEXT_PASS", "positions": 5, "last_seq": 9550, "generated_ids": [28, 665], "text": ", there"}
V43_EXIT_CODE=0
```

以上 v43 是**操作者粘贴的终端摘要**；与本次已取回 v44 `summary.json`＋logits 的证据层级不同。v43 板上 `summary.json`、逐层 checkpoint、原始 H2C/C2H 帧及所烧 bit 的身份尚未由 PC1 取回独立归档；不要把程序成功分支的断言写成已独立审计全部原始数据。PC1 的 v40–v44 host 实验源码和包目前位于本地工作目录及各自板上 WORKDIR，**并未因本文发布而自动进入 GitHub main**。

## PC2 的 v43 质量报告：事实与假设分开

PC2 提供的 `KVmix_quality_gate_20261020.md`（本地文件 SHA256 `4666D95D7ED8D2F2A49872C249685AE32EB4F4AFEA57F44CAFD73370A98DD8DC`）报告其另一次 v43 logits dump：首条 prompt 前 5 位置 board/候选 top-1 为 5/5 相同，5 位置的诊断性 `exp(mean NLL)` 为 13.47/10.51。v44 取回的首条 prompt 前 5 位置独立复算得到同样四舍五入数字（最大 logits 差 6.5310），支持**差异真实存在**。这五位置不是数据集 PPL，也没有 HF 浮点参考；不能称“B 模型质量不合格”或“FPGA 算错”。

| PC2 所提问题 | 目前可确认的边界 | 不新增上板能做什么 | 哪些判断仍需新实板证据 |
|---|---|---|---|
| position 0 的 `Once` 后 top-1 为 `):`，目标 ` upon` 的 NLL 高 | 板端和 PC 候选均如此；“目标 token 应当是 top-1”并非语言模型的正确性判据。候选/板端明确用 `add_bos=false`；本地 config 的 `bos_token_id=0` **不证明**训练时每段都自动加 BOS，也不证明此处异常由缺 BOS 引起。 | 在 PC 用相同 checkpoint/tokenizer 生成 HF float 的无 BOS 与显式 BOS 两套 logits，记录同一目标的 rank/NLL；必要时先修参考评测的输入约定。 | “板上显式 BOS 后也改善”以及改善幅度，须跑新的、有新 seq 的 B 会话。 |
| 板端与 PC 候选 logits 不相同 | v44 21/21 同前缀可比，20/21 top-1 相同，全词表最大差 6.5310；第二 prompt position0 甚至 top-1 不同。候选是 CPU F32 Attention，板端是定点 FPGA Attention，故“不 bit-exact”本身不能定位为故障。 | 用已有 v44 的逐位置 logits 和板上保存的 `wire/`、checkpoint（只读取回，无须重跑）做首处分歧分层归因；先明确容差与同数值路径 oracle。 | 若已存证据不足以重建对应层输入/输出，才需一次受控层级捕获；修正 RTL 后的真实效果仍须上板。 |
| 缺 HF float 参考，正式质量门未闭合 | 真实存在：本地已有 Smol135M checkpoint，但当前 PC Python 未装 torch/transformers/safetensors；既有 HF 资料只覆盖第0层局部张量，没有本次完整 logits。 | 在隔离的 PC 环境生成同 checkpoint、同 token/BOS 规则的 HF float logits，再离线比较 board/候选；无需 RK 或 FPGA。 | 若要声明**修正后的板端**达到 HF 容差，仍须对修正版本采集板端 logits；正式数据集 PPL/B/U/M 还需独立实验。 |
| “新 bit”的身份 | PC2 报告把其 v43 bit 声明为 `c510…`；本次 v44 声明 Plan B full bit 为 `a956…`。两次不能写成同一个 bit 的重复实验；都没有配置后独立读回哈希。 | 用各自 JTAG 下载记录、bit 文件哈希和工程版本澄清历史标签，不需再运行模型。 | 要证明 FPGA **实际配置内容**，需要设备/下载链可提供的独立配置证据；软件传入的哈希不是读回。 |

PC2 报告中的“缺 BOS 最可能”“两条路径同错所以不是 FPGA 问题”“加 BOS 后 NLL 会恢复”均是**待检验假设**，不能升级为根因。已确认的质量缺口是缺同输入的 HF 浮点基线与生产容差，而非已证实的 BOS/RTL bug。

## 目前可以继续做什么

- **PC1：** 先在 PC 离线补 HF float 的无 BOS/显式 BOS 基线及统一目标位置定义；针对 v44 第二条 prompt position0 的 top-1 分歧、前端量化与定点 Attention 做分段归因。暂不把短句 `exp(mean NLL)` 当正式 PPL，也不为追求逐 bit 相等擅改 B 架构。新硬件会话 seq 大于 11133、显式 RESET，首错不重发已追加 KV 的请求。
- **PC2：** 本轮离线质量归因没有必须新增的传输代码或上板动作；后续若执行异常恢复实验，保持 `deadline_enforced=false`，H2C 阻塞写按驱动约 10 秒上界解释，失败后单独安排完整恢复，不自动重试。
- **FPGA：** 本轮离线质量归因没有必须立即重烧的 RTL；如分段误差证明定点 Attention 超出约定容差，再据此修改相应算术并上板验证。U（全 token K2/V2、无 tail）和 M（混合层精度＋recent FP16 tail）仍未由 v44 证明。

两台 PC 的 SSH 都连接同一 RK3576。下一次实板运行仍须由一个操作者独占板卡窗口，按 [协作规则](../pcie_contract/COOPERATION.md)提前通知并获得另一方空闲确认；本文不授权重启、重烧 bit、重载驱动或其他系统级操作。

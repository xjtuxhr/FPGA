# KVmix 工程进度与团队下一步分工（2026-10-18）

**当前阶段：B 模式 Attention + DDR 已完成实板功能验证；正在准备实际 RK/NPU 输入的单层接入。** 已通过的项目包括真实模型 CPU/HF 输入对拍、不同层 K/V 隔离和非空缓存 RESET。实际 NPU→FPGA→O projection 的模型调用链、完整模型质量及 U/M 实板实验仍需推进。

本文按 2026-10-18 在 B 侧实际收到的文件、已完成的独立复核，以及本次 GitHub 同步结果整理。最新完整实板回传为 2026-10-16；本文没有重新操作板卡。PC1 已告知正在用 NPU 生成 QKV，截至本次整理尚未向 B 交付新的实际 NPU capture。

## 1. 团队共同目标与当前配置

正式模型为 **HuggingFaceTB/SmolLM-135M**，采用方案 C：RK3576J CPU/NPU 执行模型主体，PH1A90SEG324 执行 KV 管理和 Attention。

```text
PC1：RK embedding / norm / NPU QKV / 反量化 / RoPE(Q/K)
                           ↓ Q/K/V
PC2：PCIe v2 + SGDMA，传输、完成校验与故障停止
                           ↓
B：FPGA endpoint → KV DDR 写入/历史读取 → QK → softmax → PV
                           ↓ Attention output
PC2：PCIe C2H → PC1：O projection / residual / MLP / 下一层
```

| 项目 | 当前 B 功能基线 |
|---|---|
| 模型维度 | 30 层，hidden=576，Q/KV heads=9/3，head_dim=64 |
| 编译配置 | `MAX_T=64`、`LAYERS=30`、`SCORE_SHIFT=3`、`DDR_GATE=1` |
| KV 存储 | B：FP16 KV；每层独立历史，当前 token 可见自己及过去 |
| Attention 算术 | 候选 Q8.8 输入、exp LUT、Q0.16 概率、有符号 32 位 PV 累加；FP16 wire/output |
| GQA | `kv_head = q_head // 3` |
| DDR | FPGA 侧独立 256 MiB DDR3L；AXI4 128-bit，地址 28-bit |

`SCORE_SHIFT=3` 对应 D=64 时的分数缩放。**B 的“FP16”指 KV 存储，不表示 Attention 内部采用全浮点运算。** 当前功能 bit 的上下文容量是 64；先前其他 T 参数的模块综合不能证明此功能 bit 已支持 128/256。

后续实验定义沿用 [PLAN](../PLAN.md)：U=全层全 token K2/V2、无 recent tail；M=重要 K 层 K3、重要 V 层 V4、其余 K2/V2，加 recent FP16 tail。三组共享模型、RK 计算、wire 和 Attention 算术，避免把多项变化混成 KVmix 收益。

## 2. 已完成到哪里

| 工作 | 当前状态与证据 | 结论范围 |
|---|---|---|
| FPGA 基础算子 | quant/dequant、3-bit pack/unpack、QK、softmax、PV、GQA 等已有 RTL、golden 和仿真 | 单算子通过不表示量化 KV 已在 DDR 功能路径启用 |
| PCIe v2 正常传输 | RESET 32B ACK、30 轮 OP_TEST 已多次通过；新 Attention 回传也包含协议检查 | 双向传输和正常完成可用；超时能力单独验收 |
| DDR 初始化与实际读写 | DDR-only 诊断 bit 已通过四种模式、三个窗口的 AXI 写读比较；功能 bit UART 也观测到 ready | 基础读写已证实，尚非全容量/长期带宽压力测试 |
| Attention + DDR 联合工程 | 已完成 TD 综合、P&R、生成并由用户 JTAG 下载功能 bit | 真实功能工程已构建；时序覆盖边界见下文 |
| 合成输入 Attention | 首批回传独立检查 810 个原始帧、312 次 Attention，定点输出逐位一致 | 含多层用例，但其中同层间输入相同的测试不能单独证明隔离 |
| 真实模型单层输入 | CPU/HF post-RoPE 层 0、pos0–7：39 请求、78 原始帧；8 次 Attention、4,608 个 FP16 输出全部逐位一致 | 输入是真实模型数据，生成端是 PC CPU/HF |
| 不同层 K/V 与非空 RESET | 517 请求、1,034 原始帧；484 次 Attention、278,784 个 FP16 输出全部逐位一致 | 覆盖 30 层、pos0–7、两轮不同数据及哨兵；不是完整模型执行 |
| RK/NPU 模型主体 | 已有 v39 NPU 调度结果；报告 9 forwards、1,899 次 NPU 调用、270 次软件 Attention | 该阶段 Attention 为 CPU reference，不能计作 FPGA 模型闭环 |
| 实际 NPU 单层接入准备 | B 已准备导出清单、校验/参考生成器、诊断接口和交接包；15 项离线测试通过 | 未收到实际 NPU capture；新增接口尚未实板运行 |
| U/M + RPC tail 功能集成 | 相关模块已有开发/局部验证，尚无完整量化 DDR 路径和实板验收 | 下一阶段，不能计作 KVmix 已完整上板 |

### 已通过的两项关键复核

**真实模型输入：**PC1 v5 的确包含真实 SmolLM-135M post-RoPE Q/K/V，来源为 CPU/HF。B 核对 52 个文件记录、F32→FP16 输入、完整原始帧，并从实际 wire 重算定点/float64 reference。8 帧实际 FPGA 输出与定点 reference 全部相同。相对同 wire 的 float64 Attention，最大绝对误差为 `0.0057296753`，最大单帧 RMSE 为 `0.0028731977`，各帧相对 L2 为 `6.9047%–8.8864%`。是否满足模型质量要求，仍由 PC1 完成层输出和整模型评估。

**层间隔离与 RESET：**PC2 补交的 LAYER_ID_V1 已独立复核。每个 epoch、每个位置的 30 层 K/V 均不同；layer0/29 的哨兵输出分别满足预期 `+0.125/-0.25`；在所有 30 层已有 8 个位置历史后 RESET，换数据从 pos0 重建至 pos7 通过。当前不再等待这批隔离结果，也不需要为已通过用例重跑板卡。

DDR 层地址确实在 RTL 中计算：每 token K384B+V384B，共 768B；`layer_base=layer×64×768`，`token_base=layer_base+position×768`。30 层占 1,474,560B。静态 RTL、本地 AXI 地址检查与实板行为证据相互支持；目前没有实板 AW/AR 波形抓取，不将其描述为物理总线全地址验证。RESET 使逻辑历史失效，无需物理清零 DDR。

## 3. 固定使用哪版 bit

| 项目 | 固定记录 |
|---|---|
| 版本标识 | `B64S3_20261016_C510C4FB`，按文件哈希标识 |
| 功能 bit | B 本地 `E:\KVmix\fpga_attention_ddr_20261014\attention_ddr.bit` |
| bit SHA256 | `C510C4FBA08D76B82FC5B1773BF460E60E920F12488627FF4BC64D09A9FAB378` |
| TD 工程 | `E:\KVmix\fpga_attention_ddr_20261014\attention_ddr.al` |
| 工程 SHA256 | `329A4AC88294F9CDE32E67194E83D3DA0C88701E82F5BB49984C1134C6915AAE` |
| TD / 器件 | Release_2026.1_SP2.200.067，程序 build 6.2.2.200067；PH1A90SEG324，speed -2 |
| 顶层 | `imx415_pcie_top` |
| 烧录 | 用户确认 JTAG 下载；暂无成功日志/截图，精确烧录时间未记录；非 Flash 固化记录 |
| 烧后 UART | COM4、115200/8N1，清缓存后 8 秒 16 条均为 `S:A7 F:A3002030`；PLL、cal_done、ready=1，cal_err、endpoint error=0 |
| 本地冻结快照 | `E:\KVmix\fpga_release_B64S3_20261016`，301 文件及哈希清单 |

bit 身份依据是操作者声明、磁盘文件哈希、UART 与功能结果，没有从器件独立读回整个 bit 的 SHA256。本次整理不代表重新确认板卡当前仍运行此配置；下次实验开始前由操作者核对。下一次实际下载时保存 TD 成功日志即可，不必仅为补文档重新下载。

联合 P&R：LUT6=22,032、Slice=27,073、ERAM=98/272、DSP=4/240、disRAM 占用 4,712 LUT；已约束路径 setup WNS `+0.257ns`、hold WNS `+0.020ns`、TNS=0，STA 覆盖率 **99.19%**。因此当前仍存在分布式 RAM 占用及未完整覆盖的路径，不能写成“已实现不用 disRAM”或“所有时序完全签核”。

当前已实测的功能 RTL/TD/bit 主要以本地冻结包交付，**尚未完整发布为对应 Git 源码版本**。仓库旧 endpoint commit 不能直接当作该功能 bit 的源码身份。B 后续应整理可 review 的自有 RTL、构建入口与制品索引；厂商 IP、SDK、模型和 license 分别管理。

## 4. 接口与故障行为：团队必须使用同一口径

沿用 [契约 v2](../pcie_contract/contract.json)：32B header；ATTENTION=0、RESET_CACHE=1、TEST=2。Q576/K192/V192，head-major、FP16LE，Q→K→V；Q/K 已做 RoPE，V 不旋转。普通请求含头 1952B，响应含头 1184B；RESET 请求/响应各 32B。CRC32 覆盖 crc 字段置零的头和逻辑 payload。

单请求在途；seq 含 RESET 在内递增且不因 RESET 归零；各层 position 连续。完整 C2H 的长度、CRC、seq、op、layer、position 全部匹配，才表示本请求成功。现有 bit 自动按帧处理，无 start 寄存器。

当前 **没有 host 可读的应用 status BAR，也没有错误响应帧**。DDR ready 和错误可经 FPGA UART 观察。旧摄像头例程的 `BAR0 0x5C=0x56440013` 不是此 Attention endpoint 的版本号；已有 status decoder/probe 软件也不表示 FPGA 已接上对应寄存器。

| 情况 | 当前实际表现与处理 |
|---|---|
| DDR 尚未 ready | endpoint 不消费请求；前级 FIFO 可能暂存。H2C 写返回不表示已计算；RESET/TEST 也受门控 |
| DDR ready 丢失 | CDC/FIFO、解析器和历史状态复位，在途请求可能丢失；会话失效 |
| 请求非法或 Attention/AXI 错误 | 丢弃/停止该请求，不返回成功结果；KV 可能已部分变化，UART 提供诊断 |
| host 收发异常、超时、CRC/身份不符 | 进入 FAULT、停止后续层，保存证据；不得自动重试追加 KV、返回 reference 或 CPU fallback |

AXI master 的约 1 秒无进展计数不是整次 Attention 的墙钟上界，也不负责安全取消 DMA/AXI。当前没有覆盖整个计算与 C2H 的总硬件 watchdog。故障后的恢复需在另行协调的板卡窗口处理；不能假定补发一个 RESET 就能恢复所有情况。

### 当前接入阻塞：H2C deadline 尚未通过实板验证

PC2 的 10-16 补交状态明确为 **`deadline_enforced=false`**。已有失败证据表明：外层设置 5s，H2C 阻塞仍约 10s 才返回；PC2 的超时分支另记录 0.5s deadline 同样未生效。成功收发不能代替取消测试。

本次同步还发现 Git 版本差异：

- `main@b286d63` 仍含基于主线程/SIGALRM 推导 True 的旧能力声明及“Attention 未实现”的旧说明。
- PC2 分支 [`codex/pcie-deadline-attention@3e7577a`](https://github.com/xjtuxhr/FPGA/tree/3e7577a) 已含默认 False 修正（`699ae23`）、实板超时负结果和冷启动重试更新；这些不能自动当作已合入 main、已部署到实际调用路径。
- 冻结实板包的旧 Python 属性仍可能返回 True，与补交状态矛盾。PC1 不应只转发这个旧属性来放开调度；B 新诊断接口会在创建设备前按实际 False 状态拒绝。

PC2 需要统一实现、binding、status、host metadata 和故障恢复证据。PC1 保持现有接入门槛，收到并审核真实能力后再放行。不要只改 JSON/布尔值绕过。

## 5. 现在每个人具体做什么

### PC1：完成 NPU 数据与模型侧接线

| 优先级 | 工作 | 交付物 / 完成条件 |
|---|---|---|
| P0，现在进行 | 导出 RK/NPU 实际生成的 layer0、pos0–7 post-RoPE Q/K/V | 每位置 F32LE 3840B（960 元素）；日志、导出源码、模型/量化制品 hash、runtime/driver、实际 scale/反量化和 RoPE 说明、manifest |
| P0，可并行 | 交付当前 host/bridge 源码版本，核对正式调用入口和能力门控 | Git commit 或带 hash 的源码；明确谁负责帧/seq，避免双重封装；False 能力不得被旧属性覆盖 |
| P1，数据就绪后 | 审核 NPU、wire 转换、定点 Attention 的分段误差；明确接受标准 | 用本批 NPU wire 重算参考，分别报告前端量化、FP16 转换、Attention 和 O/层输出误差 |
| P1，传输门槛解决后 | 把真实 FPGA 返回接回 O projection、residual、MLP | 单层执行日志证明输出实际来自 C2H；预录重放与实时 NPU→FPGA 接线分开记录 |
| P2，单层通过后 | 扩大到 30 层 B、token 生成及质量回归 | 真实逐层输入/输出、token/logits、PPL 或既定质量指标；与同配置参考比较 |

v5 已有真实模型输入，继续作为已通过基准。新 NPU 数据因 W8/scale 等差异不应被要求与 CPU/HF v5 逐位相同；必须保留来源并使用本批输入的 reference。无需为了文件名强制 PC1 重跑，可由 B 显式适配已有 manifest。

### PC2：解决传输能力声明与故障恢复接入门槛

| 优先级 | 工作 | 交付物 / 完成条件 |
|---|---|---|
| P0，可并行 | 对齐实际运行 adapter、False 修正、10-16 binding/status 和 PC1 bridge | commit、部署文件 hash、真实 capability；清除“新 FPGA Attention 未实现”等过期说明，保留历史 run 原件 |
| P0 | 提出并验证适用的阻塞 H2C 有界处理与人工恢复流程 | 有意阻塞时的 deadline、monotonic 返回时间、driver 日志、KV/会话状态及恢复后正常回归证据；不得只用 PC 管道测试推断实板 |
| P1，前置审核通过 | 执行新 NPU 输入的 RESET + 30 TEST + 8 ATTENTION | 39 对原始 H2C/C2H、summary、日志、seq 范围、实际 bit/adapter/binding hash；发包前重新确认 seq watermark |
| P2 | 固定可复用部署与性能测量入口 | 对齐已提交的冷启动重试代码、实板部署和日志；分离证据写盘、codec、传输/等待时间 |

层间隔离的 517 请求结果已经收到且复核通过，PC2 不必为本轮重复提交或重跑。冷启动重试在 PC2 分支已有实现及成功报告；当前工作是核对部署和归档，不从零重写。

### B（FPGA）：接收 NPU 数据、守住 B 基线，再推进 KVmix

| 优先级 | 工作 | 交付物 / 完成条件 |
|---|---|---|
| P0，当前 | 保持 B64S3 功能基线，交付已准备好的 NPU 单层工具包 | bit/工程 hash、UART/失败语义、工具包 hash 可供 PC1/PC2核对；本阶段无需改 bit |
| P0，收到数据即做 | 检查 NPU 文件来源/布局/范围，生成 FP16 wire、定点与 float64 golden | 8 份输入、8 份各类参考、清单；定位 Q8.8 溢出/下溢及转换异常，不把输入问题混入硬件误差 |
| P1，新回传到达 | 独立审核 NPU 实板原始帧和数值 | actual H2C 等于本批 NPU payload；actual C2H 逐位等于新定点参考；与 PC1 一起评估层输出 |
| P1，可并行 | 整理功能 RTL/TD 的可追溯源码提交与构建说明 | 自有 RTL、约束/脚本、IP 版本参数和冻结包索引相符；在工程副本核对路径，不覆盖已验证工程 |
| P2，B 接入和数值验收后 | 将 U/M quant/dequant、metadata、RPC tail 接入真实 DDR 路径 | 先仿真迁移、组边界/3-bit packing、RESET/隔离，再另出 bit、实板对拍和容量/质量实验 |

如果后续增加状态寄存器、错误帧或全局 watchdog，应单独立项、更新接口并形成新 RTL/bit 版本及回归记录；不在现有 B 基线上暗改。

## 6. 后续联调顺序与验收

1. **并行准备：**PC1 导出真实 NPU capture 和 host/bridge；PC2 处理 deadline/恢复门槛；B 整理 B 源码、核验数据、重算 reference。PC1 导出 NPU 数据不依赖 FPGA 门槛先解除。
2. **离线核验：**来源/模型/scale/RoPE/形状/hash/有限值通过，确定数值接受标准；以实际 NPU wire 生成期望帧。旧 v5 golden 不直接用于新 NPU 输入。
3. **单层实板：**前置能力审核通过，在独占窗口执行 RESET + 30 TEST + 8 ATTENTION；对拍 39 对原始帧。配置仍为 B/MAX_T64/SCORE_SHIFT3。
4. **同进程真实接线：**NPU QKV→FPGA→O projection→层输出；证明没有软件 Attention 替代或 fallback。
5. **30 层 B：**先少量 token，再扩大到编译容量内的上下文；审核逐层误差、历史状态、生成与质量。合成 30 层隔离通过不能替代此项。
6. **U/M 和研究实验：**B 质量稳定后，验证量化 DDR 布局与 tail，再比较 B/U/M、RK-only；记录 KV 字节、DDR 流量、质量、延迟、吞吐、资源，开展 tail-only/等字节随机策略等消融。

目前没有完整模型 B/U/M 的质量或加速结论。真实输入单层记录的 host Attention RTT 平均约 10.333ms，但含协议校验与证据写盘，且仅 8 个不同历史长度样本；不得当作纯 FPGA 时间或直接外推 30 层速度。后续性能测试需另固定计时边界。

## 7. 交接材料在哪里

下列是 **B 本地或单独交付包**，本次只上传进度文档和 README，不代表这些 ZIP、模型、厂商 IP、完整功能工程或新工具源码已上传 GitHub。

| 材料 | 路径 / 用途 |
|---|---|
| CPU/HF v5 输入 | `E:\KVmix\pc1_real_attention_handoff_20261016_v5\pc_20261016_real_attention_complete_v5` |
| 真实模型单层实板回传 | `E:\KVmix\fpga_real_attention_return_20261016.zip` |
| 隔离及非空 RESET 实板回传 | `E:\KVmix\fpga_isolation_return_20261016.zip` |
| 真实输入独立审计 | `E:\KVmix\fpga_real_attention_return_audit_20261016_v2.json` |
| 隔离独立审计 | `E:\KVmix\fpga_isolation_return_audit_20261016.json` |
| B 版本/烧录/错误/地址说明 | `E:\KVmix\fpga\docs\PC1_FPGA_BASELINE_AND_ISOLATION_20261016.md` |
| NPU 单层准备说明 | `E:\KVmix\fpga\docs\NPU_SINGLE_LAYER_PREPARATION_20261016.md` |
| 可交给 PC1/PC2 的工具包 | `E:\KVmix\fpga_npu_single_layer_handoff_20261016.zip`；含清单模板、wire/reference 生成器、诊断接口及验证记录，无实际 NPU 数据 |
| 功能基线冻结包 | `E:\KVmix\fpga_release_B64S3_20261016`；工程含原始绝对路径，归档不等于已迁移可直接构建 |

关键交付包 SHA256：

```text
fpga_real_attention_return_20261016.zip
DED1C0C1B775A2B8934F3415766B87A4F7228A2B2426FFF876D0EE297E5FE661

fpga_isolation_return_20261016.zip
353D38D23C79E7EFE423B09A78165CE92AC944D1AB9F6DCFE8FE82EFC59EC853

fpga_npu_single_layer_handoff_20261016.zip
AFF03EDA929ABD729CE71B1E3C0FDD2520998A32D009ABBA8865F0429501A92B
```

本次拉取核对的远端：`main@b286d63`、B 分支提交前 `03d0f7c`、PC2 超时分支 `3e7577a`。不同分支和本地交付包的版本需要逐项对应，不能只按文件同名判断已部署。

## 8. 协作与文档维护

PC1/PC2/B 可并行编辑和离线分析，共享板卡实验按 [COOPERATION](../pcie_contract/COOPERATION.md) 协调独占窗口；FPGA 重配置、驱动/链路恢复和系统变更需明确操作范围。本文不给出可直接执行的恢复命令。

Git 继续使用各自分支，由 PC1 review 后集成 main；B 使用 `codex/fpga-kv-attention`。每次交付带 commit/hash、配置、原始证据和验收范围；不覆盖旧结果或倒改历史 manifest。

[PROJECT_STATUS](PROJECT_STATUS.md)、10-11 快照及 [10-14 Attention 交接](ATTENTION_DDR_BOARD_HANDOFF_20261014.md) 保留为历史依据。其中“Attention 尚未实现/尚待实板执行”等进度描述由本页的新证据更新；各文件的硬件版本和测试范围仍需分别核对。开放问题继续只在 [UNKNOWNS](UNKNOWNS.md) 维护，本文为进度快照，不自动关闭任何条目。

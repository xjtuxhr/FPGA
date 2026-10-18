# PC1 v40 NPU Q/K/V 交接包：B 侧离线复核（2026-10-18）

**结论：layer 0、position 0–7 的新输入已经收到，文件完整性、FP16 wire、定点/浮点参考及 39 对离线请求/期望响应全部复核通过。尚无本批 NPU 输入的实板 FPGA 回包。** 这批输入与已上板验证的 CPU/HF v5 数据不同；后续对拍必须使用本批参考。

本次只在 B 的 PC 上读取 ZIP，并用 2026-10-16 冻结的本地 B 工具重新计算；没有执行 ZIP 内的 exporter、访问 NPU/PCIe 或重新配置 FPGA。进度总览见[团队进度与分工](TEAM_PROGRESS_AND_NEXT_STEPS_20261018.md)。

## 1. 输入身份与边界

| 项目 | 实际记录 |
|---|---|
| PC1 包 | `E:\KVmix\npu_capture_v40_offline_handoff_20261018(1).zip`，154,711B |
| ZIP SHA256 | `37048D8DF65961623ABCF175DE2AD5B36F652736E26517B50D0BF7294BAF50E8` |
| 内部 capture manifest SHA256 | `C9791AE59630064B97B9593E6CCF0E2EBB2944E9A30DBB14E96493E70DC4276C` |
| 模型 | `HuggingFaceTB/SmolLM-135M`，checkpoint SHA256 `C7A387D6FE81CA6DD304AEB809BDA3932FF1BBEF3CA41C9484502F2F448DC093` |
| 声明的运行环境 | RK3576，kernel `6.1.99`，RKNN runtime `2.3.0`，NPU driver `0.9.8`；对称 W8（输出通道）+ A8（向量），INT32 累加后按实际 scale 转 F32 |
| 数据布局 | 8 个连续位置，Q[9,64]+K[3,64]+V[3,64]；每位置 960 个 F32、3840B，小端、head-major；Q/K 已做 Smol/HF `rotate_half` RoPE，V 未旋转 |
| FPGA 目标 | B / FP16 KV / `MAX_T=64` / `SCORE_SHIFT=3`，功能 bit 文件 SHA256 `C510C4FBA08D76B82FC5B1773BF460E60E920F12488627FF4BC64D09A9FAB378` |

manifest 声明 3 个 NPU context、24 次 NPU 调用及实际量化权重/scale 的哈希。包内有 exporter 源码副本与位置日志；权重/scale 文件本身未交付，因此 B 只能核查哈希声明的格式和内部一致性，不能对未交付字节做独立哈希或仅凭文件证明 NPU 硬件实际执行。输入来源按 **PC1 的 RK/NPU 运行声明和交接证据**记录。

## 2. 离线检查结果

| 检查项 | 结果 |
|---|---|
| ZIP 完整性与安全路径 | 49 个文件，ZIP 解压校验通过；展开 305,598B；按安全相对路径解到 B 工作区 |
| 包内 manifest | 所列 48 个制品的大小/SHA256 全部匹配，清单覆盖其余全部制品 |
| 原始 capture | 8 个 Q/K/V 文件 + 2 个证据文件的 10/10 大小与哈希匹配；capture manifest 本身哈希匹配 |
| 运行记录 | 1 条 BEGIN + 8 条连续 position，token ID 为 `[6403,1980,253,655,28,665,436,253]`，与 manifest 一致 |
| B 侧重算 | 使用冻结的 `npu_capture.py`、reference 和 v2 codec，从**原始 F32 capture**重新生成；包括 manifest 在内 49/49 文件与 PC1 已准备包逐字节一致 |
| B 工具包校验 | `E:\KVmix\fpga_npu_single_layer_handoff_20261016.zip`，SHA256 `AFF03EDA929ABD729CE71B1E3C0FDD2520998A32D009ABBA8865F0429501A92B`；包内校验 33/33 文件通过 |
| 协议样例 | 离线 1 RESET + 30 TEST + 8 ATTENTION，共 39 请求；所生成期望帧与 PC1 包逐字节一致 |
| 输入范围 | 8×960 个 F32 值均有限；FP16 wire 下 Q8.8 对称范围之外共 0 项 |

本地复核产物：`E:\KVmix\npu_capture_v40_audit_20261018.json`，SHA256 `766D69FCC1A5629A24BCBE8320270B87C37356E10E369EC3CEDE20FE0CC0DCA6`。原 ZIP 和重算目录分别保存在 `E:\KVmix\npu_capture_v40_received_20261018`、`E:\KVmix\npu_capture_v40_regenerated_20261018`；这些数据包和审计 JSON **没有随本文上传仓库**。交接给队友时请以文件 SHA256 核对本地副本。

### 与已验证的 CPU/HF v5 对照

同一 8 个 token ID 下，v40 与 v5 的每个位置 **960/960 个 F32 Q/K/V 元素均不同**，8 份 FP16 payload 也都不同；全部输入的最大绝对差为 `0.0612306595`。两批定点 Attention 输出中 `681/4608` 个 FP16 元素不同，最大绝对差 `0.00390625`。这说明不能把 v5 的输出逐位作为 v40 的验收值；数值差别与其各自数据来源相符，但本检查不把差别本身当作 NPU 来源的独立证明。

按 **v40 自己的 FP16 wire** 重算浮点参考后，当前候选定点 Attention 的最大绝对误差为 `0.0058094099`，最大单帧 RMSE 为 `0.0028206190`。F32→FP16 输入转换的最大绝对误差为 `0.0019464493`；另有 `207/7680` 个非零 FP16 输入在 Q8.8 转换后变为零。没有 Q8.8 范围溢出，精度是否足以支撑层输出和完整模型质量仍由 PC1 评估。

## 3. 当前版本和实板边界

PC1 包中的 `manifest.json` 写明 `board_run_status=NOT_RUN`、`readiness.hardware_ready=false`。`requests.h2c.bin`/`expected.c2h.bin` 使用 **3300–3338** 作为离线示例 seq。它们是预计请求/输出，并非已发往板卡的帧，也未确认当前板上的真实 seq watermark；PC2 不能不核对会话状态就直接重放。

PC2 10-16 状态声明为 `deadline_enforced=false`。已有板测证明阻塞 H2C 没有在配置的短 deadline 中断，旧 Python 属性的 True 不能覆盖这个实测结论。PC1 的真实 Attention 调度门槛继续保持；只有 PC2 完成并提交真实超时/恢复能力证据、PC1 审核接口与代码版本后，才能在协调好的独占窗口做这批 NPU 输入的 FPGA 对拍。**离线重算通过不能等同于新的实板结果。**

来源证据也有一处可补齐：包内 `npu_run_stdout.txt` 保存 1 条 BEGIN 和 8 条位置记录；exporter 源码在更外层 `main()` 还会打印最终 `NPU_CAPTURE_V40_PASS` 事件，但该最终控制台输出及 `summary.json` 未包含在本包。PC1 如已保存这两项及实际 host/bridge commit，可补充给团队核对，无需为补材料重跑模型。当前包足以验证离线数据和数学参考，不能独立认证省略的最终执行记录。

## 4. 下一步交接

| 负责人 | 紧接着处理 |
|---|---|
| PC1 | 审核 v40 捕获与量化来源；补已存在的完整 stdout/summary、host/bridge 版本；用 v40 自身参考比较 NPU 前端、FP16 转换、Attention、O/层输出误差并给出可接受标准 |
| PC2 | 对齐实际 adapter/binding/status 的 `deadline_enforced=false`，解决 H2C 超时和会话恢复门槛；获准后按当前真实 seq 和独占窗口运行 RESET+30 TEST+8 ATTENTION，返回实际 39 对原始帧、版本和日志 |
| B | 保持上述功能 bit 版本；PC2 回传后检查实际 H2C 等于 v40 的 FP16 payload，实际 C2H 等于 v40 新定点 golden，再与 PC1 核对层输出 |

正式实板成功的判据是：实际收发帧数量、长度、CRC、seq、op、layer、position 全匹配，8 次 Attention 的每项 FP16 输出与本批参考逐位一致，并保留原始帧及运行环境记录。之后再报告 O projection/层输出与完整模型质量。旧的 v5 实板成功和 30 层合成隔离成功继续作为已有基线，不替代这一步。

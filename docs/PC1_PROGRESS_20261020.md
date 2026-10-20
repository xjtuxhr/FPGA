# PC1 当前进度与下一轮联调入口

更新：2026-10-20（PC 接收日期）。本文供 PC2 和 FPGA 队友快速了解 **RK3576 host/NPU 侧**的实测边界；开放问题仍以 [UNKNOWNS](UNKNOWNS.md) 为唯一清单，协议仍以 [PCIe v2 契约](../pcie_contract/README.md) 为准。板端日志路径中的 2026-04-27 是未校准的板上时钟，不是本文日期。

## 一句话状态

PC1 已将 SmolLM-135M 的真实英文 prompt 送入 RK3576 tokenizer，经 30 层 NPU linear ↔ PCIe ↔ FPGA **B（FP16 KV 存储）Attention** 串行链生成两个 token，并在 RK3576 detokenize 成 `, there`。这是短文本功能闭环，**不是** HF/浮点数值一致、PPL、长上下文、吞吐量或 U/M 验收。

## 已取得的实板结果

| 阶段 | 本次能证明什么 | 不能外推成什么 |
|---|---|---|
| v40 | 第 0 层连续 8 位置，真实 NPU QKV → FPGA B Attention → NPU O/MLP 局部通过；1 RESET、8 ATTENTION、56 NPU MatMul | 30 层生成、质量、U/M |
| v41 | 30 层、单个固定 token 前向局部通过；`V41_FULL_B_PASS`、seq 9300–9330、argmax 727 | 多位置生成、逐层 HF parity |
| v43 | 英文 `Once upon a time`（4 个 prompt ID），5 个前向位置生成 ID `[28,665]`，解码 `, there`；`V43_REAL_TEXT_PASS`、exit 0、最后 seq 9550 | 正式质量、PPL、长序列、速度或故障恢复 |

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

以上是**操作者粘贴的终端摘要**。板上 `summary.json`、逐层 checkpoint、原始 H2C/C2H 帧及所烧 bit 的身份尚未由 PC1 取回独立归档；不要把程序成功分支的断言写成已经独立审计全部原始数据。PC1 的 v40–v43 host 实验源码和包目前位于本地工作目录及各自板上 WORKDIR，**并未因本文发布而自动进入 GitHub main**。

## 目前可以继续做什么

- **PC1：** 扩大 B 的 prompt 与生成长度；保存每位置的 token、logits/分数和首错 checkpoint；用同模型、同 tokenizer、同前端量化路径的 PC reference 做逐位置误差分析，再安排 PPL/吞吐量。每个新 session 显式 RESET，seq 必须大于 9550；任何帧/数值错误首错即停，不重发可能已追加 KV 的请求。
- **PC2：** 现有 v2 SGDMA transport 足以支持下一轮 B 功能扩展，当前没有必须先写的新传输功能。保留 `deadline_enforced=false`；H2C 阻塞写的最坏边界按驱动约 10 秒解释，写超时/中断后停机并单独安排完整恢复，不能静默重试。
- **FPGA：** 现有 B bit 足以进行下一轮短文本功能扩展。正式数值/质量比较前仍需完成 Attention 数值修正与独立参考对拍；之后才是 U（全 token K2/V2、无 tail）和 M（层感知混合精度＋recent FP16 tail）的 RTL、KV metadata 和上板验证。当前 v43 不代表 U/M 已可用。

两台 PC 的 SSH 都连接同一 RK3576。下一次实板运行仍须由一个操作者独占板卡窗口，按 [协作规则](../pcie_contract/COOPERATION.md)提前通知并获得另一方空闲确认；本文不授权重启、重烧 bit、重载驱动或其他系统级操作。

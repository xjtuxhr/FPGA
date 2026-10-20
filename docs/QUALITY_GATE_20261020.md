# KVmix B 质量门排查报告

日期：2026-10-20（板载 RTC 不准，系统时间显示 2026-04-27）
平台：RK3576 EVB1 V10 + 安路 PH1A90SEG324
模型：HuggingFaceTB/SmolLM-135M，方案 C，B = FP16 KV
执行：PC2 / 板卡 kvdev，SSH + 串口 COM11 @ 1500000

---

## 0. TL;DR

1. 新 bit 本身工作正常：attention 单层 8/8 bit-exact，v43 30 层端到端 PASS。
2. 但 v43 的质量门没有通过，也没有真正开始：板上只有项目自己的 PC 候选参考，没有 HF float 参考。
3. 与 PC 候选对比：5 个位置 argmax 5/5 一致，但原始 logits 不一致（最大差 6.53），board 5 位置 PPL 13.47 vs 候选 10.51。
4. 位置 0 两边同时异常：`Once` 之后应预测 ` upon`，board 和候选的 top-1 都是 `):`。这更像 **缺 BOS / position-0 OOD**，不是 FPGA 算术问题。
5. 当前不能宣称 B 的质量通过；下一步必须拿 HF logits，并先做 BOS 与 CPU-attention/FPGA-attention 隔离实验。

---

## 1. 范围与结论

本报告只讨论 **B（FP16 KV）在真实 RK NPU + 真实 FPGA attention 路径上的功能与质量探针**，不涉及 U/M，也不是数据集 PPL 评测。

结论分三层：

| 层面 | 结论 | 证据 |
|---|---|---|
| 链路/功能 | PASS | attention 8/8 bit-exact；v43 30 层 5 位置 PASS |
| 与 PC 候选的决策一致性 | PASS | 5/5 argmax 一致 |
| 数值/质量一致性 | FAIL / 未完成 | logits 不 bit-exact；无 HF 参考 |

---

## 2. 前置状态与环境

- RK3576：Debian 12 bookworm，kernel 6.1.99 aarch64，3.8 GiB RAM。
- PCIe：`21:00.0 1edb:abcd`，`Anlogic-pcie` 驱动，Gen2 x1，BAR0 1 MiB @ `0x21200000`，BAR1 64 KiB @ `0x21300000`。
- SGDMA 节点：`/dev/ANLOGIC-PCI0_{h2c_0,c2h_0,control,user}`，权限 `root:kvdev 0660`。
- 新 bit 的 sha256 仍为 operator claim：`c510c4fba08d76b82fc5b1773bf460e60e920f12488627ff4bc64d09a9fab378`，**未在设备上独立读取验证**。
- 板载实验目录中的文件名是 20261014–20261019，但 mtime 显示 2026-04-27；以目录名为准。

---

## 3. 执行记录

### 3.1 B 重烧后的恢复

B 重烧新 bit 后，第一次直接测试失败：首笔 RESET 的 H2C 写超时，dmesg 读引擎 ID 为 `0xffffffff`，BAR0/BAR1 全 `0xffffffff`，PCIe config 中 BAR=0、`COMMAND=0x0000`，链路降到 2.5 GT/s x1。判断为 JTAG 重配置后端点“假在线”，RK 侧未重新分配资源。

执行完整恢复：

```bash
systemctl stop anlogic-sgdma
rmmod anlogic_pci
echo 2a210000.pcie > /sys/bus/platform/drivers/rk-pcie/unbind
bash /home/kvdev/pcie1-fpga.sh
systemctl start anlogic-sgdma
```

恢复后：

- `lspci` 重新出现 `1edb:abcd`
- `smoke_regs.py` 读 BAR0 得到真实值（如 `0x5c=0x56440013`、`0x74=0x00000c01`）
- 链路恢复 Gen2 x1

注意：以后每次 JTAG 重烧都需要这一步，否则第一笔 H2C 会超时并让 SGDMA 进入 FAULT。

### 3.2 Attention 单层验证（新 bit）

使用 `real_attention_pkg_20261016`，PC1 真实 layer0 QKV（positions 0–7）+ golden_fixed：

- seq `9800..9838`
- 39/39 请求成功
- 8/8 attention 输出 bit-exact（mismatch=0）
- `status=passed_real_single_layer`
- 单 op 约 8.2–8.6 ms（submit ~4.2 ms、wait ~0.05 ms、readback ~4.0 ms）；p0 首包 14.5 ms

证据：

```
/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/results/newbit_20261020_03/
```

### 3.3 v43 端到端（新 bit）

使用 PC1 的 `full-text-v43.4cYRWV`，串口 root 前台运行：

- prompt：`Once upon a time`，ids `[6403,1980,253,655]`
- seq `10100..10250`
- `status=PASS_V43_B_REAL_TEXT_SHORT_GENERATION`
- `real_npu=true`、`real_fpga_attention=true`
- `cpu_attention_fallback=false`、`cpu_linear_fallback=false`
- 30 层、5 位置、150 次 attention、1055 次 NPU、151 帧
- 生成：`, there`（ids `[28,665]`）

证据：

```
/home/kvdev/work_pc1_npu/full-text-v43.4cYRWV/host/results/v43_real_text_20260427T202038_5571/
```

说明：第一次后台运行（seq 9900）被 logind 在串口会话关闭时 SIGTERM（143），没有完成请求，不算证据。有效运行是 10100–10250。

### 3.4 原始 logits dump

v43 原版只保存 `logits_sha256` 和 `argmax_id`，不保存原始 logits。为了算逐位置 NLL，复制了一份 PC2 专用副本：

```
/home/kvdev/work_pc1_npu/full-text-v43-logits.PC2
```

只改了一处：在 `host/tools/full_text_v43.py` 的 `capture()` 中额外写 `logits_p{position}.f32.bin`（49152 × F32 = 196608 B）。PC1 的原 bundle 未修改。

运行：

- seq `10300..10450`
- PASS，生成 `, there`
- 5 个 logits 文件已生成

证据：

```
/home/kvdev/work_pc1_npu/full-text-v43-logits.PC2/host/results/v43_real_text_20260427T202544_6495/
```

---

## 4. 质量对比结果

参考使用：

```
/home/kvdev/work_pc1_npu/text-v38.oySckQ/host/.fixtures/text_v38/proof/fixtures/r0_p{0..4}_head.bin
```

这是 **PC CPU W8/A8 候选**，不是 HF float 参考，也不是数据集 PPL。

读取方式：取文件最后 196608 B 作为 49152 个 little-endian F32 logits。该假设由下面的 top-1/top-5 一致性反向确认。

### 4.1 逐位置结果

| pos | 输入上下文 | target | board top1 | cand top1 | board NLL | cand NLL | max abs diff |
|---|---|---|---|---|---|---|---|
| 0 | `Once` | ` upon` (1980) | 727 `):` | 727 `):` | 10.0433 | 10.3894 | 0.9434 |
| 1 | `Once upon` | ` a` (253) | 253 ` a` | 253 ` a` | 1.0387 | 0.1960 | 3.5416 |
| 2 | `Once upon a` | ` time` (655) | 655 ` time` | 655 ` time` | 0.9813 | 0.2025 | 6.5310 |
| 3 | `Once upon a time` | `,` (28) | 28 `,` | 28 `,` | 0.1479 | 0.1607 | 2.4162 |
| 4 | `Once upon a time,` | ` there` (665) | 665 ` there` | 665 ` there` | 0.7907 | 0.8151 | 2.2319 |

关键细节：

- p0：target ` upon` 在 board 排名 **3733**、候选排名 **5159**；两边 top-1 都是 727（`):`）。
- p1：board top5 `[253,451,260,338,22360]`，候选 `[253,655,338,260,451]`。
- p2：board top5 `[655,25232,4369,1194,5814]`，候选 `[655,25232,1194,1711,9931]`。
- p3、p4 top-1 一致，但后续名次仍不同。

### 4.2 汇总

| 指标 | board | 候选 |
|---|---|---|
| argmax 一致 | 5/5 | — |
| 5 位置 mean NLL | 2.6004 | 2.3527 |
| 5 位置 PPL | **13.47** | **10.51** |
| 排除 p0 后 mean NLL | 0.7396 | 0.3436 |
| 排除 p0 后 PPL | **2.10** | **1.41** |
| 精确相等的浮点 logits | p1–p4 均为 0 | — |

说明：5 位置 PPL 只是 smoke probe，不是模型质量指标；但它足以说明 board 与候选不是同一条数值路径。

---

## 5. 问题分析

### 5.1 问题 A：位置 0 异常（board 与候选同时错）

现象：

- 读到 `Once` 后，应预测 ` upon`（1980）
- board 和候选的 top-1 都是 727（`):`）
- ` upon` 的排名分别是 3733 和 5159
- 从 p1 开始，top-1 全部正确，文本也连贯

判断：这不像 FPGA/NPU 算术问题，因为两条完全不同的路径（FPGA attention + NPU vs PC CPU 候选）在同一位置出现同样的错误。

最可能的解释：**缺少 BOS**。

- 如果 SmolLM 训练时序列以 BOS（`<|endoftext|>`, id 0）开头，真实 token 从 position 1 开始；
- 当前 `add_bos=false`，position 0 是训练分布外的状态；
- 读到第二个 token 后，上下文进入训练分布，预测恢复正常（p1–p4 全对）。

这也意味着：**当前 5 位置评分对 p0 不公平**，不能直接把 p0 的高 NLL 当作 FPGA 质量问题。需要用 BOS 重跑验证。

其他可能：候选参考本身在 position 0 的 embedding/RoPE/位置编号上有 bug；但“两条路径同错”更支持 BOS/输入约定问题。

### 5.2 问题 B：board 与候选原始 logits 不一致

现象：

- argmax 5/5 一致，但 logits 向量不 bit-exact；
- 最大绝对差 6.5310（p2）；
- p1–p4 没有任何浮点完全相等；
- 排除 p0 后，board PPL 仍高于候选（2.10 vs 1.41）。

这不是“链路坏了”，而是数值路径不同。可能来源：

1. **FPGA attention 算术**：定点/softmax/scale/累加/舍入与 CPU F32 reference 不同。layer0 的 8 个位置 bit-exact 只证明了那一组输入下的 attention 输出，不证明 30 层循环中每一层都与 CPU reference 一致。
2. **NPU W8/A8**：量化、反量化、accumulator 顺序与 PC 模拟不完全一致。v39/six-opt 的 `numeric_verified` 是限定 shape/路径的，不等于完整 30 层 + FPGA attention 的 bit-exact。
3. **参考本身不是同一路径**：`text_v38` golden 的 `attention_role=CPU_REFERENCE_ONLY`，而 v43 是真实 FPGA attention。把两者逐 float 比较，本身就混入了“attention 实现不同”这一变量。

因此，“与候选不一致”不能直接判定 board 错；它说明 **board 的分布与候选不同，需要定位到具体层/算子**。

### 5.3 问题 C：没有 HF 参考，质量门无法闭环

板上有：

- tokenizer
- W8/A8 权重与 fixture
- PC 候选 golden
- 真实 NPU/FPGA

板上没有：

- torch / transformers
- SmolLM F32 safetensors
- HF float logits

所以：

- 不能计算真正的 HF PPL / next-token accuracy；
- 不能判断 p0 的 `):` 是 HF 也这样，还是候选/board 的问题；
- 不能宣布“B 的质量通过”。

---

## 6. 这些结果能说明什么、不能说明什么

能说明：

- 新 bit 的 attention 端点和 SGDMA 链路功能正常；
- 30 层 NPU + FPGA attention 能端到端生成文本；
- board 与 PC 候选在 5 个位置上决策一致；
- board 与 PC 候选在 logits 层面不一致，且 p0 有系统性异常。

不能说明：

- B 的质量通过；
- board 的 logits 是错的（可能是候选/参考的问题）；
- board 的 logits 是对的（没有 HF 参考）；
- U/M 的任何结论；
- bitstream 的 sha 真的是 c510...（仍未独立验证）。

---

## 7. 下一步建议（按优先级）

### P0：BOS 实验

在 prompt 前加 `<|endoftext|>`（id 0），重新跑同一套 5 位置，观察：

- p0 是否不再异常；
- p1 的 ` upon` 是否变成 top-1；
- 整体 NLL 是否回到候选水平。

预期：如果 BOS 假设成立，`Once` 的预测会从 position 1 开始，p0 异常消失。

### P0：拿 HF logits

需要 PC1 提供：

- prompt ids `[6403,1980,253,655]`
- positions 0–4（加 BOS 后再加一组）
- 每位置 49152 个 F32 logits，或至少 top-k + target logprob

拿到后计算：

- board vs HF 的 argmax / NLL / PPL
- 候选 vs HF 的同样指标
- 判断 board 与候选谁更接近 HF

### P1：分离 FPGA attention 与 NPU

同一 prompt、同一 token 序列，分别跑：

1. board + CPU-attention 参考
2. board + FPGA attention

如果两者 logits 一致，问题在 NPU/量化；如果不一致，问题在 FPGA attention 算术。

### P1：逐层定位第一处发散

`text_v38` proof 里有 `r0_p*_l*.golden.bin`（逐层 tensor）。可以从 layer 0 开始，逐层比较：

- hidden / input_norm / q / k / v / q_rope / k_rope / attention / o / mlp
- 找到第一处最大差异，再判断是 attention、KV 存储还是 NPU linear。

### P2：扩展到真实质量评测

- 固定 prompt/dataset，teacher forcing 逐位置评分；
- 对比 B / U / M；
- 加 RK-only 同质量对照；
- 最后再做生产延迟与资源数据。

---

## 8. 证据与复现

### 8.1 证据路径

```
# Attention 单层（新 bit）
/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016/results/newbit_20261020_03/

# v43 端到端（新 bit）
/home/kvdev/work_pc1_npu/full-text-v43.4cYRWV/host/results/v43_real_text_20260427T202038_5571/

# v43 + raw logits dump（PC2 副本）
/home/kvdev/work_pc1_npu/full-text-v43-logits.PC2/host/results/v43_real_text_20260427T202544_6495/

# 质量对比报告
/home/kvdev/work_pc2_pcie/quality_gate_20261020/
    README.md
    report.json
    score_board.py
    parse_head.py
    v43_dump_summary.json
```

### 8.2 seq 记录

| 运行 | seq | 结果 |
|---|---|---|
| attention 单层（新 bit） | 9800–9838 | PASS，8/8 bit-exact |
| v43 后台尝试 | 9900 | 被 logind 杀掉，无有效请求，不算证据 |
| v43 端到端 | 10100–10250 | PASS，`, there` |
| v43 + logits dump | 10300–10450 | PASS，`, there` |

下一次运行必须 `start_seq > 10450`。

### 8.3 复现命令

Attention 单层：

```bash
P=/home/kvdev/work_pc2_pcie/real_attention_pkg_20261016
cd $P
python3 board_attention/runner_real_attention.py \
  --vendor-root $P \
  --data-dir $P/real_attention \
  --binding $P/pcie_transport/bindings/board_20261016.json \
  --start-seq 9800 --test-rounds 30 --timeout 5 \
  --out $P/results/newbit_20261020_03 \
  --operator-note new_bit_by_B_after_full_recovery_seq9800
```

v43（串口 root，前台，保持串口不关）：

```bash
cd /home/kvdev/work_pc1_npu/full-text-v43.4cYRWV
bash host/tools/run_full_text_v43.sh \
  /home/kvdev/work_pc1_npu/full-text-v43.4cYRWV 10100 10050
```

logits dump（PC2 副本）：

```bash
cd /home/kvdev/work_pc1_npu/full-text-v43-logits.PC2
bash host/tools/run_full_text_v43.sh \
  /home/kvdev/work_pc1_npu/full-text-v43-logits.PC2 10300 10250
```

评分：

```bash
python3 /home/kvdev/work_pc2_pcie/quality_gate_20261020/score_board.py \
  > /home/kvdev/work_pc2_pcie/quality_gate_20261020/report.json
```

---

## 9. 附录：关键文件哈希

| 文件 | sha256 |
|---|---|
| board p0 logits | `4f493fb1f093905ebb88059605e0042c3fb5774fa6a8f98d9c2cfcda3185d5a5` |
| board p1 logits | `8aa3be2d42a147697994876bac74dfbf8ef7d5ce2a018002a7e62325b52f1a11` |
| board p2 logits | `2fceca345568a90f1ec5e51e9bede91fd45fd895a9177da9e436466e8ac89992` |
| board p3 logits | `7ec74ab688f7a216f5e6fe7b8a049b0bf7e026f22ebd7a7293dbff89398d1a0b` |
| board p4 logits | `d46af12286947afc922f5eccfa2b307b9e9648dd84765a0d8ad54b85ab8dc830` |
| tokenizer.json | `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c` |
| operator-claimed bit | `c510c4fba08d76b82fc5b1773bf460e60e920f12488627ff4bc64d09a9fab378`（未独立验证） |

---

## 10. 一句话总结

**新 bit 的链路和 attention 功能是通的，v43 也能端到端出字；但质量门目前卡在“没有 HF 参考”，同时发现两个需要隔离的现象：位置 0 的 BOS/输入约定异常，以及 board 与 PC 候选在 logits 层面的数值不一致。**

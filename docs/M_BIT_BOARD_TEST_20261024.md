# M 候选 bit 实板测试记录（2026-10-24）

状态：**M 功能通路、R=32 recent FP16 tail、真实 NPU 30 层 within-tail 630 帧独立 M golden 已通过；post-tail/量化 golden、PPL/质量、B/U/M 对比尚未完成。**

- 真实日期：2026-10-24。板钟错误，板上时间显示 2026-04-27 UTC；板端时间戳不可作为日期证据。
- 测试对象：B 通过 JTAG 烧录的 M 候选版 `attention_planb_full.bit`，路径 `E:\KVmix\um_td_planb_m_readeraddr_20261023\attention_planb_full.bit`。
- 文件 SHA256（**用户提供，非板端反读**）：`67C149839565425CE450BFBCA1E998C58F4700DE0689F0A07FDC057215BBFAB1`。
- 板上可读身份：`VERSION 0xAC = 0x504C4231`（`PLB1`），与 U bit 相同；VERSION 不能区分 U/M，正式身份以文件哈希 + TD 记录为准。
- 相关 U 记录：[U_BIT_BOARD_TEST_20261024.md](U_BIT_BOARD_TEST_20261024.md)。

## 0. 结论速览

| 项目 | 结果 |
|---|---|
| PCIe / 端点 | Gen2 x1；`VERSION=0x504C4231`；`STATUS=0x11`（READY/DONE，ERR=OK） |
| 首次烧录后 BAR0 | 全 `0xFFFFFFFF`（fake-up）；完整恢复后正常 |
| RESET + 30 轮 OP_TEST | **PASS**：30/30，0 错误，全部 bit_exact |
| 真实 NPU pos0..7 | **PASS**：8/8 与 B reference 逐位一致；pos0=`694f0fe8...`（B），不是 U 的 `16bbb131...` |
| T2 tail 边界 | **PASS**：pos0..31 与 B 逐位一致；pos32 首次偏离 → tail=32 |
| 30 层 T2 sweep（pos0..63） | 30 层 `B_prefix=32`；post-tail 30×32 全部 M-distinct（0 匹配 U，0 匹配 B） |
| v44 真实 NPU 30 层 replay | **PASS（within-tail）**：630/630 与 B reference 逐位一致，全部 finite |
| 独立 M golden（v44 real NPU，within-tail） | **PASS**：630/630 与 PC1 M golden 逐位一致，0 mismatch |
| M 策略 | K3=14/18/26，V4=14/22/23，其余 K2/V2；tail=32，group=32（bring-up 候选，未冻结） |
| tail eviction / R=32 后 | **NOT COVERED**：golden max_position=10，0 帧实际量化 |
| PPL / HF parity / 质量 | **NOT RUN** |
| B/U/M 同条件对比 | **NOT RUN**：需重新烧 B/U bit 或交付对应 golden |

## 1. 环境与绑定

| 项 | 值 |
|---|---|
| 板 | RK3576 EVB1 V10，Debian 12，kernel `6.1.99 #3` SMP aarch64 |
| 端点 | `0000:21:00.0`，`1edb:abcd`；BAR0(user) 1M @`0x21200000`，BAR1(config) 64K @`0x21300000` |
| 链路 | 5.0 GT/s x1 |
| 驱动 | `anlogic_pci`（`poll_mode=1`，`h2c_timeout=10`/`c2h_timeout=10`） |
| 节点 | `/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}`（root:kvdev 0660） |
| 协议 | contract v2；binding `board_20261016.json`（binding_version 2） |
| 访问 | SSH `kvdev`；root 操作通过板载 `adbd`（本次测试环境可用） |

## 2. 恢复

JTAG 烧录后、任何 H2C 之前，BAR0 读到全 `0xFFFFFFFF`，`STATUS/CONTROL/VERSION` 均为 `0xFFFFFFFF`，属于文档记录的 fake-up 状态。执行完整恢复：

```sh
systemctl stop anlogic-sgdma
rmmod anlogic_pci
echo 2a210000.pcie > /sys/bus/platform/drivers/rk-pcie/unbind
sleep 2
/usr/local/sbin/pcie1-fpga.sh
systemctl start anlogic-sgdma
```

恢复后：

```text
VERSION 0xAC = 0x504C4231
STATUS  0xA4 = 0x00000010 / 0x00000011  READY=1, FAULT=0, ERR=OK
```

## 3. RESET + 30 轮 OP_TEST

- runner：`post_burn_20261019/board/run_op_test_seq.py`
- `--start-seq 16000 --rounds 30 --timeout 5.0`
- 结果：`status=passed_op_test_30`，`errors=0`，30 轮全部 `bit_exact=true`。
- 计时（含 runner/AbortableDevice 开销，不是裸 SGDMA）：min 0.995 ms，mean 1.203 ms，p95 1.386 ms，max 1.443 ms。
- 证据：`/home/kvdev/pcie_bringup_20261024/op_test_16000_m_bit_20261024/summary.json`

## 4. 真实 NPU pos0..7（B reference）

- 输入：PC1 交付的真实 NPU layer0 pos0..7 QKV（`pc_20261024_u_npu_v40_capture_golden/*.qkv.fp16.bin`）。
- 两轮独立 RESET 会话，结果 deterministic。
- **8/8 与 B reference 逐位一致**；pos0 输出 SHA = `694f0fe8b4936e96ead6f57fa15163404d38ffce2883c6b819a27272a0a8f3de`，即 B 路径，不是 U 的 `16bbb131...`。
- 说明：M 的 recent FP16 tail 在 pos0..7 生效。
- 证据：
  - `m_attention_probe_20261024/summary.json`
  - `m_attention_probe_20261024/m_vs_B_reference.json`

## 5. T2 recent-tail 边界

- 输入：T2 合成向量，layer0，pos0..63，`MAX_T=256`，`SCORE_SHIFT=3`。
- 结果：
  - pos0..31：**32/32 与 B reference 逐位一致**；
  - pos32：**首次偏离 B**；
  - pos32..63：既不匹配 B，也不匹配 U golden（32/32 M-distinct）。
- 观察到的 **recent FP16 tail 长度 = 32**，与 M 设计的 R=32 一致（layer0）。
- 证据：`m_tail_probe_20261024/summary.json`

## 6. 30 层 T2 sweep（policy 行为）

对 layer 0..29 分别独立 RESET，发送 T2 pos0..63：

| 指标 | 结果 |
|---|---|
| `B_exact_prefix_len` | 30/30 层均为 **32** |
| post-tail 匹配 B | 每层 0/32 |
| post-tail 匹配 U | 每层 0/32 |
| post-tail M-distinct | 每层 **32/32** |
| 输出 finite | 1920/1920 |
| `post_tail_class` | 30/30 层 `M_DISTINCT` |

解释边界：这个 build 的 post-tail 输出对所有层都不等于 U 的 K2/V2。可能是：

1. 该 build 的所有层都走了 mixed/重要路径；或
2. M 的 reader/quantization 路径与 U bit 不同（即使层不是 important，也不会与 U 逐位相同）。

仅凭该 sweep 不能区分二者，也不能断言 important layer 集合。需要 B 的策略（K3/V4 层 ID、group/scale）和独立 M golden。

- 证据：
  - `m_layer_sweep_20261024/summary.json`
  - `m_layer_sweep_20261024/finite_check.json`

## 7. v44 真实 NPU 30 层 replay（positions ≤10）

PC1 交付 `v44_real_npu_qkv_for_m.zip`，内容：

- `qkv/`：630 个真实 NPU QKV 文件（1920 B each）；
- `manifest.json`：
  - `schema = REAL_NPU_QKV_FROM_V44_B_FOR_M_FIXED_REPLAY_V1`
  - `source_status = PASS_V44_B_TWO_PROMPTS_NUMERIC_CAPTURE`
  - `source_real_npu = true`，`source_real_fpga_attention = true`
  - **`m_bit_executed = false`**
  - **`m_expected_outputs_included = false`**
  - `max_position = 10`
  - **`m_recent_tail_or_group_transition_covered = false`**
- 两个请求：request0 11 位置、request1 10 位置；每位置 30 层；共 630 帧。

实板 replay 规则：每个请求先 RESET，然后 position-major / layer-minor 按 manifest 顺序发送。

结果：

```text
total_frames = 630
bit_exact vs B reference = 630
mismatch_count = 0
all_finite = true
final_reset_seq = 18932
```

因为所有位置 ≤10 < R=32，这个结果验证的是 **M recent FP16 tail 内部、30 层真实 NPU 输入** 的 B/FP16 等价性；**不验证** pos≥32 的 tail 驱逐/迁移，也不是独立 M golden。

- 证据：
  - `/home/kvdev/pcie_bringup_20261024/v44_real_npu_qkv_for_m/`
  - `m_real_npu_30layer_20261024/summary.json`
  - `m_real_npu_30layer_20261024/vs_B_reference.json`
  - `m_real_npu_30layer_20261024/outputs/`（630 个 attention 输出）

## 7.5 独立 M golden（v44 real NPU，within-tail）

PC1 随后交付 `m_v44_real_npu_golden_20261024.zip`：

- `expected_m_attention_request_position_layer.fp16.bin`：630 × 1152 B，SHA256 `1079d16b...17addb`；
- `input_qkv_request_position_layer.fp16.bin`：630 × 1920 B，SHA256 `634beb0c...ee394`；
- `manifest.json`：630 条记录，逐帧 input/output offset + SHA256；
- golden 状态：`INDEPENDENT_SOFTWARE_GOLDEN_NOT_BOARD_VERIFIED`；
- policy 状态：`BRINGUP_CANDIDATE_NOT_FROZEN_NOT_QUALITY_VALIDATED`；
- policy SHA256：`65b876bd56d6458a8b416f13719cf4688f1fafad48ab82675ef29a8f9a13173c`。

候选 M 策略：

| 层 | K/V 位宽 |
|---|---|
| K3：14 / 18 / 26 | K3 |
| V4：14 / 22 / 23 | V4 |
| 其余层 | K2 / V2 |

另：`tail_length=32`，`group=32`。该策略是首轮联调候选，不是质量评测后冻结策略。

实板 630 帧对拍结果：

```text
status = PASS_M_V44_REAL_NPU_GOLDEN_630
frames = 630
bit_exact = 630
mismatch_count = 0
input_frame_mismatches = []
bit_config_counts = {"2K/2V": 525, "3K/2V": 42, "2K/4V": 42, "3K/4V": 21}
kv_actually_quantized_frames = 0
tail_eviction_covered = false
m_quantization_exercised = false
```

这说明：该 M bit 在真实 NPU 输入、30 层路由、双请求 RESET、R=32 tail 内部，与 PC1 独立 M golden **630/630 逐位一致**。由于所有位置 ≤10，实际 K/V 全部仍在 FP16 tail 中，`kv_actually_quantized_frames=0`；**没有验证任何 K3/V4 量化、旧 token 迁移或 tail 驱逐**。

证据：

- `/home/kvdev/pcie_bringup_20261024/m_v44_real_npu_golden_20261024/`
- `/home/kvdev/pcie_bringup_20261024/m_real_npu_30layer_20261024/vs_M_golden.json`

## 8. 结论与边界

**已证明**

- M bit 可恢复、RESET/TEST/ATTENTION 通路正常。
- 真实 NPU pos0..7 与 B reference 逐位一致。
- recent FP16 tail 长度 = 32（layer0，T2 0..63；30 层 sweep 的 B prefix 均为 32）。
- 630 帧真实 NPU 30 层输入（positions ≤10）与 B reference 逐位一致，全部 finite。
- 同一 630 帧与 PC1 独立 M golden 逐位一致（630/630，0 mismatch），包括 K3=14/18/26、V4=14/22/23 的策略配置。

**未证明**

- pos≥32 的 tail 驱逐、K 组重算、迁移正确性；
- K3/V4 实际量化误差（本 630 帧 `kv_actually_quantized_frames=0`）；
- PPL / HF parity / 模型质量；
- B/U/M 同条件对比；
- 生产 dtype / PCIe packet / 端到端性能。

**特别说明**：候选策略为 K3=14/18/26、V4=14/22/23、其余 K2/V2、tail=32、group=32。30 层 T2 sweep 的 post-tail 全部 M-distinct，包括非重要层；如果 M 的 K2/V2 路径与 U 逐位相同，非重要层 post-tail 应匹配 U，但实际没有。这说明该 M build 的 post-tail reader/quant 路径可能与 U 不同，或 T2 sweep 的 U 对比不足以解释 M 的迁移算法。需要 post-tail M golden（README 提到的 `m_candidate_golden_20261024.zip`）来定位，不能据此判定 M 质量。

## 9. 证据清单

板上根目录：`/home/kvdev/pcie_bringup_20261024/`

| 路径 | 内容 |
|---|---|
| `op_test_16000_m_bit_20261024/` | RESET+30 TEST |
| `m_attention_probe_20261024/` | 真实 NPU pos0..7，两轮；B reference 对拍 |
| `m_tail_probe_20261024/` | T2 0..63 tail 边界 |
| `m_layer_sweep_20261024/` | 30 层 × T2 0..63 policy sweep + finite check |
| `v44_real_npu_qkv_for_m/` | PC1 交付的 630 QKV + manifest |
| `m_real_npu_30layer_20261024/` | 真实 NPU 30 层 replay + `vs_B_reference.json` + `vs_M_golden.json` |
| `m_v44_real_npu_golden_20261024/` | PC1 独立 M golden：manifest、expected blob、policy |
| `m_bit_compact_20261024/` | 上述结果的紧凑汇总 |
| `scripts/` | 探针脚本（含 `compare_m_golden.py`） |

GitHub 副本：`docs/evidence/m_bit_20261024/`（紧凑汇总 + 脚本 + policy + `vs_M_golden.json`）。原始 630 QKV、630 attention 输出、725 KB expected blob 和全量 summary 仍只在板上，未全部上传。

## 10. 复现命令

恢复（root；本次通过 `adbd`）：

```sh
systemctl stop anlogic-sgdma
rmmod anlogic_pci
echo 2a210000.pcie > /sys/bus/platform/drivers/rk-pcie/unbind
sleep 2
/usr/local/sbin/pcie1-fpga.sh
systemctl start anlogic-sgdma
lspci -nn | grep 1edb
```

OP_TEST：

```sh
python3 /home/kvdev/work_pc2_pcie/post_burn_20261019/board/run_op_test_seq.py \
  --vendor-root /home/kvdev/work_pc2_pcie/pc2_consistent_20261016 \
  --binding /home/kvdev/work_pc2_pcie/pc2_consistent_20261016/pcie_transport/bindings/board_20261016.json \
  --start-seq 16000 --rounds 30 --timeout 5.0 \
  --out /home/kvdev/pcie_bringup_20261024/op_test_16000_m_bit_20261024 \
  --operator-note "M attention_planb_full.bit sha 67C14983...; 2026-10-24"
```

真实 NPU pos0..7 / tail / sweep / replay 脚本见 `scripts/`（`m_probe.py`、`m_tail_probe.py`、`m_layer_sweep.py`、`m_real_npu_replay.py`）。这些脚本内 `OUT`/`START` 固定；复测需改 `OUT` 并递增 `START`，不能回退 seq。

## 11. 未完成 Gate

1. **M golden**：v44 real NPU within-tail 630 帧已 PASS；仍需 post-tail/量化 golden（README 提到的 `m_candidate_golden_20261024.zip`，位置 0–64）验证 pos31/32/33 驱逐。
2. **M 策略**：候选已确认 K3=14/18/26、V4=14/22/23、其余 K2/V2、tail=32、group=32；但仍是 bring-up 候选，未冻结、未做质量验证。
3. **tail eviction**：需要 positions ≥32 的连续输入/golden，验证驱逐、重算、迁移；当前 630 帧 `kv_actually_quantized_frames=0`。
4. **PPL / HF parity / 质量**：PC1 环境。
5. **B/U/M 对比**：需 B/U bit 或对应 golden。
6. **C2H poll-mode 瞬态**：见 U 记录；3328 帧未复现，诊断 harness 就位。

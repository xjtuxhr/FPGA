# U 候选 bit 实板测试记录（2026-10-24）

状态：**U 候选 bit 的功能通路和 layer0 U golden 已通过；PPL/质量、B/U/M 对比尚未完成。**

- 真实日期：2026-10-24。板钟错误，板上时间显示 2026-04-27 UTC；本文所有板端时间戳不可作为日期证据。
- 测试对象：B 通过 JTAG 烧录的 U 候选版 `attention_planb_full.bit`，本地路径 `E:\KVmix\um_td_planb_u_dequantpipe_20261023\attention_planb_full.bit`。
- bit 文件 SHA256（**B 提供，非板端反读**）：`B5AD8F911EC270E448993D09C1BC243B4420D873870B3B18D39BD46A2958B26B`。
- 板上可读身份：`VERSION 0xAC = 0x504C4231`（`PLB1`），与 B 的 Plan B 接口版本一致。该版本字不能唯一区分 bit，正式证据仍以 B 的烧录文件哈希和 TD 日志为准。

## 0. 结论速览

| 项目 | 结果 |
|---|---|
| PCIe 链路 | Gen2 x1（5.0 GT/s），`21:00.0 [1edb:abcd]`，`anlogic_pci` 已加载 |
| 端点状态 | `VERSION=0x504C4231`，`STATUS=0x11`（DONE/READY，ERR=OK） |
| RESET + 30 轮 OP_TEST | **PASS**：30/30，0 错误，全部 bit_exact |
| U Attention 合成向量 pos0..7 | **PASS**：两轮 RESET 会话，逐位一致，全部 finite |
| U Attention 长上下文 256 | **PASS**：3 次独立会话共 768 次 Attention，256 个输出三次逐位一致，全部 finite |
| U 30 层文本生成（v44 路径） | **PASS**：两次独立运行，生成 token 完全一致 |
| U golden：真实 NPU layer0 pos0..7 | **PASS**：8 帧连续对拍，逐位一致，0 mismatch |
| U golden：T2 合成 256 位置 | **PASS**：256/256 逐位一致，concat SHA 相同 |
| U vs B/float 数值诊断 | 差异随 context 增大而下降，未发散；不是 golden |
| C2H 首次超时诊断 | 8 帧 golden 运行未触发；harness 已就位，首次超时即落盘 |
| PPL / HF parity / 质量 | **NOT RUN**：需 PC1 的 HF/PPL 环境 |
| B/U/M 同条件对比 | **NOT RUN**：需重新烧 B/M bit |

## 1. 环境与绑定

| 项 | 值 |
|---|---|
| 板 | RK3576 EVB1 V10，Debian 12 bookworm，kernel `6.1.99 #3` SMP aarch64 |
| 主机内存/存储 | 3.8 GiB RAM，根分区 14G（约 67% 已用） |
| 端点 | `0000:21:00.0`，`1edb:abcd`；BAR0(user) 1M @`0x21200000`，BAR1(config) 64K @`0x21300000` |
| 链路 | 5.0 GT/s x1 |
| 驱动 | `anlogic_pci`（`poll_mode=1`，`h2c_timeout=10`/`c2h_timeout=10`） |
| 节点 | `/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}`（root:kvdev 0660） |
| 协议 | contract v2；binding `board_20261016.json`（binding_version 2） |
| 访问路径 | SSH `kvdev`；root 操作通过板载 `adbd`（本次测试环境可用） |

`adbd` 是调试接口，本次仅用于执行恢复；这不代表常规操作路径，也不改变 `kvdev` 不在 sudoers 的事实。

## 2. 端点状态与恢复

B 烧完 JTAG bit 后、任何 H2C 之前，端点先出现：

```text
STATUS 0xA4 = 0x00000062  DONE=0 READY=0 FAULT=1 BUSY=1 ERR=SEQ(1)
CONTROL 0xA8 = 0x00000000
```

判断为 JTAG 重配前遗留的 host 请求/seq 状态被新 bit 收到。随后写入 `CONTROL.SOFT_RESET=1`（BAR0 `0xA8`，自清零）：

```text
第一次 SOFT_RESET: STATUS = 0x00000028  FAULT=1 BUSY=0 ERR=AXI_DDR(4)
第二次 SOFT_RESET: STATUS = 0x00000028
等待 45 s:         STATUS = 0x00000028  （READY 从未置 1）
```

即 `SOFT_RESET` 清掉了 `SEQ/BUSY`，但没有清掉 `AXI_DDR` 锁存。随后做完整恢复（stop driver → rmmod → rk-pcie unbind → PERST/rebind → insmod）：

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
VERSION = 0x504C4231
STATUS  = 0x00000010 / 0x00000011  READY=1, FAULT=0, ERR=OK
```

结论：`AXI_DDR` 是**残留会话/未完成 AXI 事务**导致的锁存，不是该 U bit 的 DDR 路径永久故障；完整 PERST/rebind 可清除。该现象对 B 的 `SOFT_RESET` 清除范围是一个待确认点。

## 3. RESET + 30 轮 OP_TEST

- runner：`/home/kvdev/work_pc2_pcie/post_burn_20261019/board/run_op_test_seq.py`
- binding：`/home/kvdev/work_pc2_pcie/pc2_consistent_20261016/pcie_transport/bindings/board_20261016.json`
- `--start-seq 10000 --rounds 30 --timeout 5.0`
- 结果：`status=passed_op_test_30`，`errors=0`，30 轮全部 `bit_exact=true`。
- 计时（含 `AbortableDevice` 线程/轮询与证据落盘开销，**不是裸 SGDMA 延迟**）：
  - min 0.542 ms，mean 1.234 ms，p95 1.629 ms，max 2.017 ms。
- 该 runner 的 `deadline_enforced=false`；H2C 仍受驱动 10 s 上界约束。
- 证据：`/home/kvdev/pcie_bringup_20261024/op_test_10000_u_bit_20261024/summary.json`

## 4. U Attention 合成向量

### 4.1 pos0..7

- 输入：`attention_pkg_20261014/board_attention/vectors.py` 的 T2 合成向量，layer0，pos0..7，`score_shift=3`，`MAX_T=64`。
- 两轮独立 RESET + Attention：
  - 全部 `finite`，无 FAULT/CRC/seq 错误；
  - 两轮输出逐位一致（`deterministic_across_reset=true`）。
- 输出 SHA256（pos0..7）：

```text
0: 94ed0f559b98c357c6dd1b36747561d14c34b77905682c34cdffe0c02e46a038
1: 5131ecc3c055733a7334fcdca8280ecc1c16b8a8c972fc95ff2b6f336d089e3f
2: be1c6aa80cd1558565e81f2598548268827ac42f6cd86963184c27c9c3ebe5d6
3: fa21d916801e28cc99d099198a5de006f5dd763059985def7572ed7fbb940850
4: 1dfff2aa1cb07dc33ac8e286c2e896ab99f6e695f54f8983922e76019690a214
5: 4fce783d25c0f879d1efa91b3f3a4d3a5c7e3f1ff7d74987b83294af20cd60cf
6: cab4273569c454135d1bcfbf364603b9220fc873c846aecae54c7baf4e200a4d
7: 7106e02bf65062b8508fd47c4d989f0564ce8023baa36266e0ab37c2a45590a5
```

- 证据：`/home/kvdev/pcie_bringup_20261024/u_attention_probe_20261024/`（summary + 每帧 h2c/c2h/json）。

### 4.2 长上下文 pos0..255

- 同一 T2 向量，layer0，pos0..255，`MAX_T=256`，`score_shift=3`。
- 三次独立 RESET 会话，共 768 次 Attention：
  - 全部 `finite`，无 FAULT；
  - 256 个位置的输出在三次会话中逐位一致；
  - 拼接输出 `SHA256=045d90a02533cfc1675531f5a147276299f1c3ce9ec1222fd4b547cd28c79976`。
- 延迟（transport RTT，不含文件写入；单次请求）：

| 位置/T | 延迟 |
|---:|---:|
| 0 / 1 | 0.934 ms |
| 1 / 2 | 1.825 ms |
| 2 / 3 | 2.400 ms |
| 3 / 4 | 3.000 ms |
| 7 / 8 | 5.302 ms |
| 15 / 16 | 9.953 ms |
| 31 / 32 | 19.314 ms |
| 63 / 64 | 37.487 ms |
| 127 / 128 | 73.861 ms |
| 191 / 192 | 110.185 ms |
| 255 / 256 | 146.450 ms |

- 近似线性：约 0.57 ms / context token（DERIVED）。
- 若按 30 层、每层同样 T=256 的 Attention 粗略外推，Attention-only 约 4.4 s/token；这是由合成单层数据推导，**不是端到端实测**。
- 证据：`/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_outputs_20261024/summary.json`

## 5. 30 层 U 文本生成（v44 路径）

原始 PC1 包 `/home/kvdev/work_pc1_npu/full-text-v44-planb.q4RMWe` 是 **B 模式**，且硬编码 B bit SHA 与 B probe 期望，未改动。为在 U bit 上跑通，复制到：

```text
/home/kvdev/pcie_bringup_20261024/u_full_v44_20261024/
```

副本仅修改：

- `host/tools/full_text_v44.py`：`PLANB_BIT_SHA256` → U 文件 SHA（小写）；`PROBE_OUTPUT_SHA256` → U 实测 probe 输出；scope/事件名 B→U。
- `host/.fixtures/v44_probe/attention_l0_p0.output.bin` → 用 U bit 对同一真实 layer0 pos0 输入的实测输出替换。
- `host/tools/run_full_text_v44.sh`：`--operator-bit-sha256` → U SHA；结果目录名 `v44_u_expansion_*`。

真实层0 pos0 probe：

```text
input SHA256  = 42de7ec4bc029f4e0a726b38777060158713884d4d69732372db340f5bf2cd9e
B 期望 SHA256 = 694f0fe8b4936e96ead6f57fa15163404d38ffce2883c6b819a27272a0a8f3de
U 实测 SHA256 = 16bbb13180d5156c299eaa019f37d5915a512713bf3c2ff6dea50f0d917f1d8b
两者不同字节数 = 477 / 1152（U 的 K2/V2 量化导致，符合预期）
```

运行参数：2 个 prompt、每个最多 8 个新 token、30 层、`start_seq` 分别为 10200 和 11800（两次独立会话）。

两次运行生成 token **完全一致**：

| Prompt | 生成文本 | token IDs |
|---|---|---|
| `Once upon a time` | `, there was a little girl named Lily` | `[28, 665, 436, 253, 1838, 8180, 3365, 14176]` |
| `The little girl` | ` was a little girl. She was a` | `[436, 253, 1838, 8180, 30, 2306, 436, 253]` |

每次运行：2 个 prompt 请求、21 个位置、630 次 Attention、2 次 prompt RESET（另有 1 次 probe RESET），`EXIT_CODE=0`。

与 B 版结果不同（B 第一次为 `, there was a curious little girl named`，第二次含换行 token），符合 U 与 B 的 KV 精度差异；这是功能差异，不是质量结论。

v44 summary 明确标记：

```text
status = PASS_V44_U_TWO_PROMPTS_NUMERIC_CAPTURE
quality_gate_passed = False
hf_parity_passed = False
um_verified = False
production_latency_measured = False
```

**重要边界**：该 v44 的 probe 期望来自 U bit 自身的实测输出，只能证明“同一输入在 U bit 上可复现”，**不是独立 U golden**。它不能替代 B 提供的仿真/参考向量做数值正确性验收。

证据：

- run1：`/home/kvdev/pcie_bringup_20261024/u_full_v44_20261024/host/results/v44_u_expansion_20260427T203630_21839/`
- run2：`/home/kvdev/pcie_bringup_20261024/u_full_v44_20261024/host/results/v44_u_expansion_20260427T204614_25941/`
- 每个结果目录含 `summary.json`、`logits/`、`wire/`、`probe/`、`run.log` 和 `*.portable.tar.gz`。
- 真实层0 probe 原始帧：`/home/kvdev/pcie_bringup_20261024/u_full_v44_probe_20261024/`

## 5.5 U golden 对拍（PC1 交付）

PC1 于 2026-10-24 交付 `pc1_u_board_report_match_20261024.zip`，其中包含真实 RK NPU layer0 pos0..7 的 U 参考：

```text
pc_20261024_u_npu_v40_capture_golden/
  manifest.json
  pos000..pos007.qkv.fp16.bin        (1920 B each)
  pos000..pos007.attention.fp16.bin  (1152 B each)
pc_20261024_u_npu_v40_capture_golden_v2.json
pc_20261024_u_t2_256_golden.json
score_u_npu_capture.py
score_u_t2_stream.py
```

manifest 状态为 `PC1_INDEPENDENT_U_NPU_CAPTURE_GOLDEN_NOT_BOARD`；输入为 post-RoPE Q/K，边界和 U 量化语义由 PC1 产生，**不是板端反推**。

实板 8 帧连续对拍：

- RESET seq 12500，随后 pos0..7 连续 seq 12501..12508，layer0，binding v2，单请求 timeout 12 s。
- 结果：**8/8 `bit_exact=true`，`mismatch_bytes=0`**；每帧 board SHA256 与 manifest `output_sha256` 完全一致。
- 延迟（transport RTT）：1.034 / 1.825 / 2.448 / 3.093 / 3.761 / 4.148 / 4.752 / 5.324 ms。
- 收尾 RESET seq 12509；`VERSION=0x504C4231`，`STATUS=0x11`（DONE/READY，ERR=OK）。
- 证据：`/home/kvdev/pcie_bringup_20261024/u_npu_golden_8frame_20261024/`

同一交付包还包含 T2 合成 256 位置的 golden。用板上已保存的 256 个输出逐位比较：

```text
positions_compared = 256
mismatch_count = 0
golden_concatenated_output_sha256 = 045d90a02533cfc1675531f5a147276299f1c3ce9ec1222fd4b547cd28c79976
board_concatenated_output_sha256  = 045d90a02533cfc1675531f5a147276299f1c3ce9ec1222fd4b547cd28c79976
status = PASS_U_T2_256_GOLDEN_BIT_EXACT
```

证据：`/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_outputs_20261024/u_t2_256_golden_compare.json`

这也回答了此前 v44 probe 的独立性问题：probe 的 pos0 U 输出 `16bbb131...` 与 PC1 golden 的 pos0 输出一致；T2 256 的 concat SHA `045d90a0...` 也与 PC1 golden 一致。此前基于板端自测值的 probe 不是偶然自洽，而是与 PC1 的独立 U 参考逐位相同。

**C2H 首次超时诊断**：8 帧 golden 运行没有出现 C2H 超时，因此没有生成 `diag_first_c2h_timeout/`。对拍 runner `scripts/u_npu_golden_8frame.py` 已内置诊断：首次 C2H/H2C 超时或 golden mismatch 时立即 fail-stop，并在关闭设备前保存 dmesg、BAR0 STATUS/VERSION/CONTROL、链路速度/宽度、驱动参数、transport 状态、当前帧和 `diagnostic.json`，不自动重试、不自动 reset/recovery。

## 6. U vs B/float 数值诊断

说明：B reference 是 `attention_pkg_20261014` 的 B 模式候选参考（FP16 KV、Q8.8、exp-LUT），**不是 U golden**。该表只用于观察 U 量化误差随 context 的趋势。

| pos/T | max abs(U−B) | RMSE(U,B) | RMSE(U,float) |
|---:|---:|---:|---:|
| 0 / 1 | 0.480469 | 0.278031 | 0.277493 |
| 1 / 2 | 0.335938 | 0.156141 | 0.155835 |
| 2 / 3 | 0.332031 | 0.126389 | 0.126401 |
| 3 / 4 | 0.285156 | 0.105923 | 0.105484 |
| 7 / 8 | 0.222656 | 0.072025 | 0.071817 |
| 15 / 16 | 0.117188 | 0.046381 | 0.046369 |
| 31 / 32 | 0.066406 | 0.027484 | 0.027344 |
| 63 / 64 | 0.042969 | 0.016058 | 0.016002 |
| 127 / 128 | 0.031250 | 0.012353 | 0.012518 |
| 191 / 192 | 0.023438 | 0.010628 | 0.010694 |
| 255 / 256 | 0.019531 | 0.010504 | 0.010629 |

趋势：误差随 context 增长而下降，未出现发散，说明 U 的 K2/V2 历史在大 T 下仍保持稳定。该表不能替代 U golden。

证据：`/home/kvdev/pcie_bringup_20261024/u_attention_ctx256_outputs_20261024/u_vs_B_metrics.json`

## 7. 异常记录：C2H poll-mode 瞬态超时

在一次“每个 Attention 后穿插 Python B-reference 计算”的诊断运行中（`u_attention_ctx256_metrics_20261024`），约 pos>127 时出现：

```text
Polling timeout occurred
desc_wb = 0x00000000, expected 0x00000002
0-C2H0-ST xfer ...,1184, s 0x1 timed out, ep 0x4a0
completed_desc_count = 0x2
SG engine 0-C2H0-ST status: 0x00000000
abort transfer ...
```

- 端点自身仍为 `STATUS=0x11`（READY/DONE，无 FAULT）。
- host transport 进入 FAULT；完整恢复后正常。
- 干净连续运行 512 次（256×2）和 256 次（另一次）均 0 错误，输出逐位一致。
- 判断：host/driver `poll_mode=1` 的 C2H 完成通知偶发丢失，与 U bit 的 Attention 数值无关；需 PC2 继续跟踪（现有 H2C deadline 文档未覆盖 C2H 完成丢失）。
- 该失败运行的 `summary.json` 保留在 `u_attention_ctx256_metrics_20261024/`，**不要**把其中的部分结果当作 Gate；长上下文数据以 `u_attention_ctx256_outputs_20261024/` 的干净三次一致结果为准。
- 2026-10-24 的真实 NPU 8 帧 golden 对拍**没有**触发 C2H 超时；`u_npu_golden_8frame_20261024/` 下没有 `diag_first_c2h_timeout/`。该 runner 的诊断路径已保留，下一次首次超时会自动落盘。

## 8. 证据清单

根目录：`/home/kvdev/pcie_bringup_20261024/`

| 路径 | 内容 |
|---|---|
| `status_20261024.txt` | 初次连接/链路/驱动状态 |
| `newbit_planb_u_probe_20261024.txt` | VERSION/STATUS、SOFT_RESET、AXI_DDR 现场 |
| `op_test_10000_u_bit_20261024/` | RESET+30 TEST，summary + 每轮帧 |
| `u_attention_probe_20261024/` | 合成 T2 pos0..7，两轮 RESET |
| `u_attention_ctx256_20261024/` | 256 位置 ×2 轮，determinism |
| `u_attention_ctx256_outputs_20261024/` | 256 位置干净输出 + `u_vs_B_metrics.json` |
| `u_attention_ctx256_metrics_20261024/` | 穿插 B-reference 的失败诊断（保留，不作 Gate） |
| `u_full_v44_probe_20261024/` | 真实 layer0 pos0 的 U 输出（probe 期望来源） |
| `u_full_v44_20261024/` | 打补丁的 U v44 副本；run1/run2 结果与 portable tar.gz |
| `pc_20261024_u_npu_v40_capture_golden/` | PC1 交付的真实 NPU pos0..7 U golden（qkv + attention + manifest） |
| `pc_20261024_u_npu_v40_capture_golden_v2.json` | 同一 golden 的扁平 JSON |
| `pc_20261024_u_t2_256_golden.json` | PC1 交付的 T2 256 U golden |
| `u_npu_golden_8frame_20261024/` | 8 帧真实 NPU golden 对拍：summary + 每帧 request/response/golden |
| `u_attention_ctx256_outputs_20261024/u_t2_256_golden_compare.json` | T2 256 golden 256/256 对拍结果 |
| `scripts/` | 本次使用的探针脚本（ctx256、8-frame golden、metrics、v44 probe 等） |

GitHub 副本：`docs/evidence/u_bit_20261024/`（探针脚本 + 8 帧 summary + T2 256 对拍结果）。PC1 的 golden binary 和板上原始逐帧数据未全部上传；golden 的 manifest/hash 以本文和板上目录为准。

## 9. 未完成 Gate 与边界

1. **U golden 覆盖范围**：真实 NPU layer0 pos0..7 和 T2 256 已 **PASS**；尚未覆盖 30 层逐层、其他 prompt、HF float logits 或数据集 PPL。需要 PC1 继续交付对应 golden。
2. **PPL / HF parity / 质量**：需 PC1 的 HF/PPL 环境；v44 明确 `quality_gate_passed=false`、`hf_parity_passed=false`。
3. **B/U/M 同条件对比**：需要重新烧 B/M bit；当前板上是 U bit，旧 B 结论不能沿用。
4. **C2H poll-mode 完成丢失**：PC2 需复核；8 帧 golden 对拍未触发，未定位根因；首次超时诊断 harness 已就位。
5. **生产数值格式/延迟**：本次是 v2 FP16 测试 profile；不代表生产 dtype、scale、PCIe packet 或端到端性能。
6. **bit 身份**：文件 SHA 由 B 提供，板端只能读 `VERSION=0x504C4231`；`VERSION` 不能唯一区分 bit。
7. **时间**：板钟错误约 6 个月，所有板端 `generated_utc`/mtime 不可用。

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
  --start-seq 10000 --rounds 30 --timeout 5.0 \
  --out /home/kvdev/pcie_bringup_20261024/op_test_10000_u_bit_20261024 \
  --operator-note "U attention_planb_full.bit sha B5AD8F91...; 2026-10-24"
```

U v44（在打补丁的副本中；需 root 以执行 `runuser`）：

```sh
cd /home/kvdev/pcie_bringup_20261024/u_full_v44_20261024
KVMIX_V44_B_EXPANSION_APPROVED=YES \
KVMIX_V44_U_EXPANSION_APPROVED=YES \
KVMIX_PC2_IDLE_CONFIRMED=YES \
KVMIX_TEMP_VIDEO_APPROVED=YES \
bash host/tools/run_full_text_v44.sh \
  /home/kvdev/pcie_bringup_20261024/u_full_v44_20261024 11800 11757
```

真实 NPU 8 帧 U golden（脚本内 `OUT`/`START` 固定；复测需改 `OUT` 和递增的 `START`）：

```sh
python3 /home/kvdev/pcie_bringup_20261024/scripts/u_npu_golden_8frame.py
```

T2 256 U golden 对拍（使用已保存的 256 个输出）：

```sh
python3 /home/kvdev/pcie_bringup_20261024/scripts/compare_t2_256.py
```

合成 Attention 探针脚本见 `scripts/`；每次都从 RESET 开始，seq 必须大于之前所有已尝试 seq。

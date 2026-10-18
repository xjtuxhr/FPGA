# v40 单层受控运行报告（2026-10-18）

- 作者：PC2
- 任务：在独占窗口保存本批 `RESET + 30 TEST + 8 ATTENTION` 的真实 H2C/C2H 帧
- 输入：PC1 `npu_capture_v40_offline_handoff_20261018`（实际 RK/NPU QKV）
- 位宽/配置：B / FP16 KV / MAX_T=64 / LAYERS=30 / SCORE_SHIFT=3
- 状态：**39/39 请求通过；8/8 Attention 与 v40 golden_fixed 逐位一致**

## 1. 受控条件

- `deadline_enforced=false` **如实保留**；使用 `--accept-h2c-write-not-deadline-bounded`。
- 任一超时/错误立即 fail-stop；不自动重发、不追加 KV、不 CPU/mock fallback。
- 真实 session 是 recovery 后**唯一一个 H2C 进程**；运行前无其他 H2C 进程。
- 实际 seq：**6000**；RESET=6000，TEST=6001–6030，ATTENTION=6031–6038。
- 离线包占位 seq 是 3300–3338，**未重放**；`offline_seq_reused=false`。
- 驱动：原版 `anlogic_pci`（SHA256 `fb04231e…1007e`）；未装 abort 测试驱动。
- bit：操作者声明 `C510C4FBA08D76B82FC5B1773BF460E60E920F12488627FF4BC64D09A9FAB378`。
- binding：`board_20261016.json`；vendor 源 hash 记录在 manifest。

运行命令：

```bash
runner_v40.py \
  --vendor-root .../pc2_consistent_20261016 \
  --data-dir .../v40_offline_20261018 \
  --binding .../board_20261016.json \
  --start-seq 6000 --test-rounds 30 --timeout 5.0 \
  --out .../v40_results_20261018_run_6000 \
  --accept-h2c-write-not-deadline-bounded \
  --operator-note 'PC2 controlled v40 single-layer: ...'
```

## 2. 结果

```text
status: passed_real_single_layer
requests: 39
reset_acks: 1
test: 30
attention: 8
last_validated_seq: 6038
elapsed_s: 0.546807
```

独立复核（本地重新解析 39 对原始帧）：

```text
counts reset/test/attention: 1 30 8
frame/CRC/seq/op/layer/position: OK
H2C Attention payload == v40 payloads_fp16: OK
C2H Attention payload == v40 golden_fixed: OK
TEST echo: 30/30 OK
errors: NONE
seq_range: 6000-6038
```

计时（含 host transport/证据落盘，不是纯 FPGA 时间）：

```text
TEST      n=30  min 8.332ms  mean 9.120ms  p50 8.886ms  p95 11.260ms
ATTENTION n=8   min 9.182ms  mean 9.406ms  p50 9.495ms  p95 9.613ms
```

## 3. 证据

- 本地：`C:\Users\meitianle\AppData\Local\Temp\opencode\v40_results_run_6000`
- 板卡：`/home/kvdev/work_pc2_pcie/v40_results_20261018_run_6000`
- 119 文件：39×(`.h2c.bin`/`.c2h.bin`/`.json`) + `manifest.json` + `summary.json` + `HASHES.txt`
- ZIP：`C:\Users\meitianle\Documents\FPGA\v40_run_6000_20261018.zip`
- 仓库证据：`docs/evidence/v40_run_6000_20261018.zip`（打包证据；原始日志仍以板卡目录为准）
- ZIP SHA256：`d4ba00e5c302d79adf8ef310917997f7f7caeefcf2ace817ce066bed1e121793`

## 4. 边界

- 这是当前 B64S3 功能 bit 的受控单层运行；**没有** host 可读 STATUS/FAULT/DONE，也不是 B 的新 bit。
- `deadline_enforced` 仍为 false；本次成功不代表硬 deadline 已解决。
- 运行后 SGDMA engine 可能不能被下一个 H2C 进程复用；已按计划 recovery，未重试。
- 输入来源是 PC1 声明的实际 RK/NPU capture；B 已离线复核，但本报告不做独立 NPU 溯源。
- 计时含协议校验与证据落盘，不能当纯 FPGA 计算时间，也不能外推 30 层吞吐。

## 5. 下一步

1. B 确认 0xA4/0xA8 并实现 STATUS/CONTROL/SOFT_RESET，新 bit。
2. PC2 用 `StatusTransport + AbortableDevice` 跑 N1–N10。
3. PC1 审核本批 C2H，接 O projection/层输出。
4. 新 bit 回归通过后，再扩大到 30 层/U/M。

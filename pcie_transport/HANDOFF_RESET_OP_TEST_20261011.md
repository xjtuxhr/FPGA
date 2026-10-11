# 交接证据：RESET + 30 轮 framed v2 OP_TEST（2026-10-11）

状态：**板测已通过（不重复跑）**。作者：PC2。范围：`RESET_CACHE` + 30 轮 `OP_TEST` 的传输层验收证据。

## 1. 标识

| 项 | 值 |
|---|---|
| 协议 | 契约 v2（`protocol_version=2`）、`binding_version=1`、`wire_dtype=fp16_le` |
| 端点 bitstream | `imx415_pcie_4k.bit` sha256 `8FA867D7075D42C4B6943C5CEF01342863EEDBFA41187943F49F0C08E5CEBEF9`（v2 endpoint） |
| 端点器件 | `1edb:abcd`，`20:00.0`(桥)/`21:00.0`；`PHASE9_VERSION 0x56440013`；Gen2 x1 |
| binding 文件 | `pcie_transport/bindings/board_20261011.json`，sha256 `cbd9d704384b7c20fee59a53924489ba13025cdb849b503e05e3e87ac195372a` |
| 源码（板测版本） | `main@fa0ea2e`（`sgdma_device.py` + binding）；host plugin `main@2f4a35d`（`host_plugin.py`） |
| 设备节点 | `/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}`（`root:kvdev 0660`） |
| 驱动 | `Anlogic-pcie`/`anlogic_pci`（2020.8.21，poll_mode=1，`h2c_timeout=10`/`c2h_timeout=10`） |

## 2. 准确命令

部署（PC→板）：`pcie_contract/` + `pcie_transport/` 解到 `/home/kvdev/optest_v2/`。
运行（官方 runner）：

```bash
cd /home/kvdev/optest_v2
PYTHONPATH=. python3 -m pcie_transport.tools.run_op_test_on_board \
    --binding pcie_transport/bindings/board_20261011.json --rounds 30 --timeout-s 5.0 \
    --out host/results/op_test_20261011
```

host plugin 冒烟（走 PC1 的 `make_transport` 接口）：`/home/kvdev/optest_v2/plugin_smoke.py`。

## 3. 结果

`host/results/op_test_20261011/op_test_summary.json`：

```json
{ "rounds": 30, "errors": 0,
  "profile": "framed_v2 (1952B/1184B logical frames)",
  "min_s": 0.000199, "mean_s": 0.000289, "max_s": 0.000436, "p95_s": 0.000414,
  "total_s": 0.00867, "reset_timing_s": 0.000605,
  "backend": "board", "device": "pcie_transport.sgdma_device",
  "binding_version": 1, "contract_version": 2, "reset_timing_s": 0.000605 }
```

- **错误数 = 0**（30/30 逐字节比对 + CRC/seq/layer/position 全对）。
- plugin 冒烟：`BOARD_PLUGIN_OK 5`（RESET 32B + 5 轮 OP_TEST）。

### 延迟口径

- **framed v2**（H2C 1952B = 32B 头 + 1920B；C2H 1184B = 32B 头 + 1152B）。
- 每轮 `total = submit + wait + readback + verify`（`rounds.csv` 逐列给出）。
- `OP_TEST` 是**回显**：**不含 Attention**、不改 KV；往返已含 FPGA 处理。
- `roundtrip` 仅反映本 binding/驱动/bitstream/机器；**不是** P99 可靠性承诺、也不含 DMA padding 之外的对齐开销。
- 逐轮明细：`host/results/op_test_20261011/op_test_rounds.csv`（板上；本仓库 `evidence/` 属 gitignore 本地 artifact）。

## 4. 能力声明（准确口径）

| 能力 | 状态 |
|---|---|
| `RESET_CACHE`(op=1) | ✅ 已验证（32B ack） |
| `OP_TEST`(op=2) | ✅ 已验证（回显前 1152B） |
| `ATTENTION`(op=0) | ❌ **未实现**（endpoint 占位，需 DDR） |
| KV 写入 / 策略配置 | ❌ **未实现** |
| 应用 status 字 | ❌ 未接；完成靠 C2H 帧 + SGDMA |
| `metadata().attention_supported` / `policy_configured` / `kv_write_supported` | 均 `false` |

PC 端负例（PC-only，非板测）：`pcie_transport/tests/test_transport.py` 覆盖短写/超时/旧帧/CRC→FAULT；
`tests/test_host_plugin.py` 覆盖 plugin 层短写/超时/旧帧/CRC；`tests/test_sgdma_deadline.py` 覆盖有界写机制。

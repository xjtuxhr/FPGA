# 板卡快照与工作进度（2026-10-11）

更新：2026-10-11。本文是一次**串口实测盘点**记录，用于对照 [PROJECT_STATUS](PROJECT_STATUS.md)（2026-09-30）与 [PC2 PCIe1 bring-up 报告](PC2_PCIE1_BRINGUP_REPORT_20261006.md)。结论区分 **FACT**（板上直接读到）与解释；开放问题仍只以 [UNKNOWNS](UNKNOWNS.md) 为准。

> 板卡时钟错误（文件 mtime 显示 2026-04），故文件时间戳不作为证据。

## 1. 方法与边界

- 经串口 `COM11`（USB-Enhanced-SERIAL CH9102，板上 `ttyFIQ0`，1500000 8N1）以 root shell 执行命令。
- 观察部分只读；**PCIe 重建**使用了板上已验证的 `/usr/local/sbin/pcie1-fpga.sh`（写 `vcc3v3_pcie` gpio-124、脉冲 PERST# gpio-48、rebind `rk-pcie`），经操作者授权。
- 未改 DTB/驱动/systemd/网络；未跑任何厂商一键脚本。
- 边界：本文只反映当日实测。**framed `OP_TEST` 通过只证明 v2 transport，不证明 `ATTENTION`、数值或模型质量**；不关闭任何 UNKNOWN。

## 2. 系统环境 FACT

| 项 | 值 |
|---|---|
| OS | Debian GNU/Linux 12 (bookworm) |
| kernel | `6.1.99 #3` SMP aarch64 |
| host | `linaro-alip` |
| 内存 | 3.8 GiB（空闲 3.4 GiB） |
| root | `/dev/mmcblk0p6` ext4 14G，用量 54% |
| `/userdata` | `/dev/mmcblk0p8` ext4 15G，用量 1% |
| 网络 | `end0=192.168.137.101/24`（PC2）、`end1=192.168.138.101/24`（PC1），NetworkManager 持久化 |
| SSH | sshd 监听 22 |
| NPU | RKNPU driver **v0.9.8**；`/dev/dri/{card0,card1,renderD128,renderD129}`、`/dev/mpp_service` |

## 3. PCIe / FPGA：当日先 DOWN，重建后 UP（FACT）

### 3.1 开机后（DOWN）

| 项 | 观察 |
|---|---|
| DT status | `pcie@2a200000`=disabled；`pcie@2a210000`=okay |
| 服务 | `pcie1-fpga`、`anlogic-sgdma` 均 enabled+active |
| 内核日志 | `rk-pcie 2a210000.pcie: PCIe Link Fail, LTSSM is 0x3, hw_retries=0/1` → `failed to initialize host` |
| `lspci` | 空；无 `/dev/ANLOGIC-PCI0_*` |

**解释（非实测结论）**：控制器已使能、驱动/服务在位，但**开机时链路训练失败**（LTSSM 0x3 = Polling 无对端），`rk-pcie` 失败后**不自动重试**。最可能是**上电/PERST 竞争**：`pcie1-fpga.service` 只跑一次，那一瞬 FPGA/供电/复位还没就绪。与 2026-10-06 报告的 link up 相比是**时序回退**，不代表 bit 丢失；**冷启动大概率会复现**。

### 3.2 手动重建后（UP）

执行（脚本开头若已枚举会**直接跳过**，所以先强制 unbind）：

```sh
echo 2a210000.pcie > /sys/bus/platform/drivers/rk-pcie/unbind
sleep 2
/usr/local/sbin/pcie1-fpga.sh
```

结果 FACT：

| 项 | 值 |
|---|---|
| 桥 / 端点 | `20:00.0 [1d87:3576]`；`21:00.0 [1edb:abcd]` |
| BAR | BAR0(user) 1M@`0x21200000`，BAR1(config) 64K@`0x21300000` |
| 节点 | `/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}`（`root:kvdev 0660`） |
| 链路 | `PCIe Link up, LTSSM is 0x130011` → `PCIe Gen.2 x1 link up` |
| 寄存器 | BAR0 `0x5C=0x56440013`（PHASE9_VERSION）、`0x74=0x00000c01`（link_up=1）、`0x84=0x00002001` |

**另一坑 FACT**：一次失败的 DMA 会把 PCIe/驱动打进降级态（BAR 全读 `0xffffffff`、SGDMA `engine id missing`）。上述 unbind+脚本可**完整恢复**。

## 4. 当前 bitstream（由 B 提供）

| 项 | 值 |
|---|---|
| 文件 | `imx415_pcie_4k.bit` |
| SHA256 | `8FA867D7075D42C4B6943C5CEF01342863EEDBFA41187943F49F0C08E5CEBEF9` |
| 大小 | 4850323 B |
| 类型 | **v2 endpoint**（非 10-06 的 RAW 回环 bit） |
| 加载方式 | **JTAG 直接配置运行中的 FPGA**（不固化 flash）；重烧后链路会掉，需重训 |

B 说明的 v2 实现现状：`RESET_CACHE(op=1)` ✅ 回 32B ack；`OP_TEST(op=2)` ✅ 回显请求 payload 前 1152B；`ATTENTION(op=0)` ❌ 未实现（占位，真算需 DDR）；status 字（`[0]DONE/[3:1]ERR`）❌ 尚未接到 endpoint，完成靠 C2H 帧 + SGDMA 完成。

## 5. framed v2 `OP_TEST`：30 轮 0 错误（FACT）

使用一个复用板上 `pcie_contract/contract.py` 的独立 runner（`/home/kvdev/op_test_v2.py`）直接对 `h2c_0`/`c2h_0` 收发 framed v2 帧，帧格式/校验与契约 v2 一致（`run_op_test_on_board.py` 因 `sgdma_device` 仍 fail-closed、无 real binding 暂不能直接跑）。

```text
op_test_v2 framed rounds=30 timeout=3.0 H2C=1952 C2H=1184
RESET_OK seq=1 ack=32 bytes t_us=819.1
RESULT OK=30 bad=0 err=0
roundtrip us: min=63.0 mean=235.6 p50=195.7 p95=382.5 max=419.4 total=7067.1
```

- `RESET_CACHE`：收到 32B ack ✅
- `OP_TEST`：30 轮串行、逐字节比对、CRC/seq/layer/position 全对、**错误 0** ✅
- 单层 framed 往返 **P50 ≈ 196µs / P95 ≈ 383µs**（H2C 1952B + C2H 1184B，含 32B 头）

这属于契约里的 **framed v2** profile，可记为 transport 层 `OP_TEST` 通过。

## 6. 回环（RAW loopback）的定位

- **未验证，且对当前 bit 不适用**：`pcie_loopback.py` 发的是裸 1920B（无帧头），v2 endpoint 会当帧头解析、自然不回数据（表现为 `Polling timeout` / `SGDMA BUSY`）。此前用它是**方法错误**，不是硬件故障。
- **已被 framed `OP_TEST` 取代**：`OP_TEST` 同样验证 H2C→C2H 双向，且额外校验 header/CRC/seq/length 并逐字节比对，覆盖并超过裸回环。
- 结论：回环**不作为里程碑**；回环 bit + `pcie_loopback.py` 仅留作**二分诊断工具**（回环过/OP_TEST 不过 ⇒ endpoint 逻辑问题）。

## 7. PC1（host/NPU）进度 FACT

`/home/kvdev` 有 v14–v39 批处理与制品；`work_pc1_npu/` 下逐算子/集成 gate：`kv-system-v9`、`real-q/k/v/o-gate v15–v18`、`real-mlp-up/-gate/-down/-chain v19–v23`、`mlp-timing-v24`、`mlp-bulk-gate-v25`、`qkv-stage-v26`、`six-opt-v27`、`tail-profile-v28`、`packed-snapshot-v29`、`input-split-v30`、`block-candidate-v31`、`block-sequence-v32`、`layer-pair-v33`、`full-forward v34–v36`、`greedy-v37`、`text-v38`、`integration-v39`。

运行脚本共同特征：强制串口 root 后降权到 UID1002 `kvdev`；要求操作者确认 **PC2 idle**；校验 sha256；不装依赖、不重传模型、无自动重试。

RTL 侧 `fpga_kv_attention/`（KVmix 量化/反量化、QK/softmax/PV、GQA、B 通路）已 iverilog 仿真 + TD 综合通过；T256 GQA ERAM 79/272、DSP 4/240、Fmax 78MHz，但**未接 PCIe endpoint/DDR**。

## 8. 最新 v39（integration）结果 FACT

`work_pc1_npu/integration-v39.tS25uh/`：状态 `PASS_INTEGRATION_READY_V39_REFERENCE`；`real_npu=true`、`numeric_verified=true`；样例 `"Once upon a time"`→`", there"`、`"The little girl"`→`" was a"`；2 requests / 9 forwards / 1899 NPU calls / 270 attention calls。

**未通过/未执行**：`fpga_verified=false`、`pcie_gate_passed=false`、`full_gate_passed=false`、`physical_pcie_executed=false`、`fpga_attention_executed=false`、`model_quality_passed=false`、`hf_execution_parity_passed=false`；`attention_role=CPU_REFERENCE_ONLY`。

## 9. 结论

- **PCIe 链路 + 驱动 + v2 framed transport（`OP_TEST`）在真实端点、真实 PCIe 上已验证通过**（30 轮 0 错误）。这是相对仓库文档（2026-10-06 停在 RAW 回环/未接 v2）的实质推进。
- 仍未闭合：**`ATTENTION(op=0)` 未实现**；NPU/host 侧 v39 仍用 CPU reference attention，`physical_pcie_executed=false`。
- 因此“方案 C”的 **FPGA Attention 环节尚未接入**；transport 已就绪，等 endpoint 的 attention 通路。

## 10. 下一步（建议，非授权动作）

1. **B 实现 `ATTENTION(op=0)`** endpoint（需 DDR），再接单层 `ATTENTION` 测试。
2. **修冷启动 PCIe 时序**：`pcie1-fpga.sh` 里上电后加延时/重试，或把 bind 改成幂等重训，避免每次冷启动都 STOP+手动重建。
3. 可选：把 framed `OP_TEST` 压力加大（100 轮 / p99），并把 summary 落成板上证据文件；把 standalone runner 交给 PC2 复用。
4. PC1：v39 host/handoff 源码纳入版本控制（当前仅在板上）。

本文为实测快照，不关闭 [UNKNOWNS](UNKNOWNS.md) 任何条目。

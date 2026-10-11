# 板卡快照与工作进度（2026-10-11）

更新：2026-10-11。本文是一次**串口只读盘点**的实测记录，用于对照当前 [PROJECT_STATUS](PROJECT_STATUS.md)（2026-09-30）与 [PC2 PCIe1 bring-up 报告](PC2_PCIE1_BRINGUP_REPORT_20261006.md)。结论区分 **FACT**（本次在板上直接读到）与解释；开放问题仍只以 [UNKNOWNS](UNKNOWNS.md) 为准。

> 板卡时钟错误（文件 mtime 显示 2026-04），故文件时间戳不作为证据。

## 1. 方法

- 经串口 `COM11`（USB-Enhanced-SERIAL CH9102，板上 `ttyFIQ0`，1500000 8N1）以 root shell 执行**只读**命令（`cat`/`ls`/`lspci`/`dmesg`/`systemctl`）。
- 未改动 DTB、驱动、systemd 服务、网络或任何文件；未运行任何厂商一键脚本。
- 边界：本文只反映**本次开机后**状态，不代表历史实验是否通过，也不构成 NPU/PCIe/Attention Gate 证据。

## 2. 系统环境 FACT

| 项 | 值 |
|---|---|
| OS | Debian GNU/Linux 12 (bookworm) |
| kernel | `6.1.99 #3` SMP aarch64 |
| host | `linaro-alip` |
| 内存 | 3.8 GiB（空闲 3.4 GiB，used 436 MiB） |
| root | `/dev/mmcblk0p6` ext4 14G，用量 54% |
| `/userdata` | `/dev/mmcblk0p8` ext4 15G，用量 1% |
| 网络 | `end0=192.168.137.101/24`（PC2）、`end1=192.168.138.101/24`（PC1），均 UP，由 NetworkManager 连接 `pcie-end0`/`pcie-end1` 持久化 |
| SSH | sshd 监听 22，enabled+active |

## 3. PCIe / FPGA 现状：当前 DOWN（FACT）

| 项 | 观察 |
|---|---|
| DT status | `pcie@2a200000`=disabled；`pcie@2a210000`=okay |
| 服务 | `pcie1-fpga` enabled+active；`anlogic-sgdma` enabled+active |
| 内核日志 | `rk-pcie 2a210000.pcie: PCIe Link Fail, LTSSM is 0x3, hw_retries=0/1` → `failed to initialize host` |
| `pcie1-fpga.sh` | `PCIe1 NOT enumerated` |
| `lspci` | 空（无 `1edb:abcd`） |
| 设备节点 | 无 `/dev/ANLOGIC-PCI0_*` |
| 模块 | `anlogic_pci` 已加载，use count=0 |
| bitstream | 板上未找到任何 `.bit` |

**解释（非实测结论）**：控制器已使能、驱动/服务在位，但链路训练失败（LTSSM 0x3 = Polling 且无对端）。与 2026-10-06 报告（link up + 回环 P50 118µs）相比**发生回退**。最可能原因是**掉电后 FPGA 未重新加载 endpoint bitstream**（SERDES 无对端），其次是 PERST#/电源 GPIO 时序。需 FPGA 老师/现场用 JTAG 或厂商流程重烧 `imx415_pcie_4k.bit` 后复测。

## 4. NPU 现状 FACT

- RKNPU driver **v0.9.8**。
- `/dev/dri/{card0,card1}`、`renderD128`、`renderD129`、`/dev/mpp_service` 均存在。

## 5. PC1（host/NPU）工作进度 FACT

`/home/kvdev` 下存在 v14–v39 的批处理脚本与制品；`work_pc1_npu/` 下有逐算子/集成 gate 目录：

- 数值/算子 gate：`kv-system-v9`、`real-q-gate-v15`、`real-k-gate-v16`、`real-v-gate-v17`、`real-o-gate-v18`、`real-mlp-up/-gate/-down/-chain v19–v23`、`mlp-timing-v24`、`mlp-bulk-gate-v25`、`qkv-stage-v26`
- 优化/结构：`six-opt-v27`、`tail-profile-v28`、`packed-snapshot-v29`、`input-split-v30`、`block-candidate-v31`、`block-sequence-v32`、`layer-pair-v33`
- 端到端：`full-forward v34/v35/v36`、`greedy-v37`、`text-v38`、`integration-v39`

运行脚本（v37/v38/v39）共同特征（FACT，读自板上脚本）：

- 强制串口 root（`ttyFIQ0`）后降权到 UID1002 `kvdev`（组 `users,render,video`）运行；
- 要求操作者确认 **PC2 idle**（operator assertion，非 Agent 独立验证）；
- 校验传输包 sha256；禁止系统/依赖安装；不重传模型；无自动重试。

## 6. 最新一轮 v39（integration）结果 FACT

`work_pc1_npu/integration-v39.tS25uh/`（`outcome.txt` / `console.log`）：

- 状态：`PASS_INTEGRATION_READY_V39_REFERENCE`
- 真实 NPU：`real_npu=true`、`numeric_verified=true`
- 生成样例：`"Once upon a time"`→`", there"`；`"The little girl"`→`" was a"`（`MAX_NEW_TOKENS`）
- 规模：2 requests / 9 forwards / 1899 NPU calls / 270 attention calls / 4810 checkpoint records
- **未通过/未执行**：`fpga_verified=false`、`pcie_gate_passed=false`、`full_gate_passed=false`、`physical_pcie_executed=false`、`fpga_attention_executed=false`、`model_quality_passed=false`、`hf_execution_parity_passed=false`
- `attention_role=CPU_REFERENCE_ONLY`：Attention 目前是 CPU reference，不是 FPGA。

## 7. PC2（PCIe）进度 FACT

`work_pc2_pcie/`：`fit_dtb_patch.py`、`patch_pcie1_dtb.py`、`probe_enumeration.sh`、`run_pcie1_bringup.sh`、`PCIE_BRINGUP_RUNBOOK.md`、`VENDOR_PCIE_REFERENCE.md`、`evidence/`（仅一份 2026-10-05 probe 日志）。

## 8. 与仓库文档的差异 / 结论

- 仓库 docs（2026-09-30 / 10-06）停留在“NPU 尚未 benchmark、PCIe 刚打通回环”的阶段；**实板进度已推进到 v39 的 NPU+host 软件集成并能出 token**。
- 但 FPGA Attention 与物理 PCIe **当前均未接通**：v39 明确 `attention_role=CPU_REFERENCE_ONLY`、`physical_pcie_executed=false`；且板卡 PCIe 现在链路失败。
- 因此“方案 C”链路整体尚未闭合：RK/NPU 侧软件可用，FPGA 侧离线 RTL（`fpga_kv_attention/`）仿真/综合通过但未接入 endpoint 与 DDR。

## 9. 下一步（建议，非授权动作）

1. 由 FPGA 老师/现场重新加载 endpoint bitstream（JTAG 或厂商流程）；确认 PERST#（gpio-48）、`vcc3v3_pcie`（gpio-124）时序。
2. 复测 PCIe 枚举（`lspci` 应见 `1edb:abcd`）+ `/dev/ANLOGIC-PCI0_*`，再跑 RAW 1920B 回环。
3. 链路恢复后推进 v2 framed（RESET/OP_TEST/ATTENTION），并按 [TRANSPORT_BINDING](../pcie_contract/TRANSPORT_BINDING.md) 填 binding。
4. PC1 侧把 v39 host/handoff 源码纳入版本控制（当前仅在板上，未提交 main）。

本文为只读快照，不关闭 [UNKNOWNS](UNKNOWNS.md) 任何条目。

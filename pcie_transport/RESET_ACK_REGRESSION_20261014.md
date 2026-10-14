# PC2 板测记录：冷启动修复 + endpoint RESET 异常【已修复并通过 30 轮】（2026-04-27）

状态：**RESOLVED** — 冷启动已修复并重启验证；endpoint RESET/OP_TEST 在 B 的新 bit 上复测通过（30 轮 0 错误）。作者：PC2。开放问题仍以 [UNKNOWNS](../docs/UNKNOWNS.md) 为准，本文件不复制独立清单。

板钟异常（文件 mtime 显示 2026-04），时间戳以 uptime/串口为准，不作为证据。

## 0. 结论速览

| 项 | 结果 |
|---|---|
| 冷启动链路 | 原 5 次/34 s 重试失败；已加固并**软重启验证自动 up**（~18.8 s） |
| endpoint RESET | 旧 bit：seq=magic、CRC 每帧变、自由运行洪泛 → 新 bit：**单发 1 个 32B ACK**，seq/CRC 正确 |
| OP_TEST | 新 bit：**30 轮 0 错误**（跑两遍），p50≈185–198 µs，p95≈335–338 µs |
| 关键操作点 | JTAG 重配后链路会「假 up」，**必须做完整恢复**（rmmod+unbind+PERST+insmod）才生效 |

## 1. 环境与身份

| 项 | 值 |
|---|---|
| 板 | `linaro-alip`，Debian 12，kernel `6.1.99 #3` SMP aarch64 |
| 端点 | `21:00.0 [1edb:abcd]`；BAR0(user) 1M@`0x21200000`，BAR1 64K@`0x21300000`；Gen2 x1 |
| 驱动 | `anlogic_pci` 2020.8.21（`poll_mode=1`，`h2c_timeout=10`/`c2h_timeout=10`） |
| 节点 | `/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}`（root:kvdev 0660） |
| 访问 | SSH `linaro`（在 `sudo` 组；**`kvdev` 不在 sudoers**）；root 经 `sudo` |
| 协议 | 契约 v2，binding `board_20261011.json` |
| 版本寄存器 | BAR0 `0x5C=0x56440013` —— **摄像头例程版本号，不能区分 endpoint 版本**；识别只能用 bit 文件 SHA256 |

## 2. FACT：冷启动时序问题与修复

- 冷启动 `lspci` 空、`dmesg`：`PCIe Link Fail, LTSSM is 0x3`（Polling，无对端）。
- 原加固版脚本（`MAX_ATTEMPTS=5`，~34 s 窗口）确实执行了 `retry 1/5..5/5` 但全部失败；且失败仍 `exit 0`，systemd 不重启。
- 手动 `unbind rk-pcie` + `/usr/local/sbin/pcie1-fpga.sh` 几分钟后**首次尝试即成功** → FPGA 已配置，非 bitstream 丢失。
- **修复**：`pcie1-fpga.sh` 改为 先等 gpio/regulator 子系统 + 5 s settle，重试窗口扩到 45 次（~3 min），最终失败 `exit 1`；service 增 `Restart=on-failure`/`RestartSec=10`/`TimeoutStartSec=0`。
- **验证（FACT）**：软重启后自动 `PCIe Link up, LTSSM is 0x130011` / `Gen.2 x1`（uptime ~18.8 s），端点自动枚举、节点齐全。强制 down 后 `systemctl restart pcie1-fpga` 8.3 s 恢复。
- 备份：`/home/kvdev/pcie1_backup_20260427_201438/`（原脚本/服务/ko）。

## 3. 原异常（旧 bit）与根因

旧 bit 行为：干净 rebind 后 C2H 安静；**一发 `RESET`(op=1) 就异常**，两种表现：自由运行洪泛（2 s 读出 1.5–6.9 MB）或 `errno 512` 无响应。洪泛帧解码：

```text
op=1 layer=0xff pos=0 seq=0x584d564b(=magic) plen=0 crc=每帧不同
```

B 仿真定位根因（与板测一致）：`ddr_ready=0` 时 H2C `READY=0`，状态机仍按 VALID 读数据，FIFO 没出队而把第一拍当第二拍 → `seq` 变 magic；旧 RESET 分支跳过 CRC 校验直接发 ACK → 洪泛 + CRC 变化。
B 修复：握手、RESET 校验、响应 CRC 锁存、FIFO 两侧复位；新增双时钟回归 62 用例、Attention 51 用例与 T=1~256 历史测试通过。

## 4. FACT：新 bit 复测通过

- B 的新 bit 由 JTAG 烧录：文件名 **`imx415_pcie_4k.bit`**，SHA256
  **`165E2B976C38BC1826F0D89B5A53D29910189D8B93CD9D7A40A921A23C9F840F`**
  （与 10-11 `8FA867D7…5CEBEF9`、10-12 本地候选 `7EF9E334…2AE86` **均不同**）。
  文件名与旧版相同，**只能靠 SHA256 区分**；板上无法从软件读出加载文件。
- **JTAG 重配后链路「假 up」**：`lspci` 仍显示 `1edb:abcd`，但直接 `OP_TEST` 会在 **H2C 写**就 `errno 512`。完整恢复后才生效：

  ```sh
  systemctl stop anlogic-sgdma; rmmod anlogic_pci
  echo 2a210000.pcie > /sys/bus/platform/drivers/rk-pcie/unbind; sleep 2
  /usr/local/sbin/pcie1-fpga.sh
  systemctl start anlogic-sgdma
  ```

- 结果：

  ```text
  SINGLE_RESET_OK seq=0x11223344 crc=0xbd168fc5      # 恰好 1 个 32B ACK，seq 正确回显
  ACK 之后无多余输出（errno512 = 无数据；洪泛消失）

  op_test_v2 30 轮（两遍）:
    RESET_OK seq=1 ack=32 bytes
    RESULT OK=30 bad=0 err=0
    us min=61~83  mean=191~220  p50=185~198  p95=335~338  max=336~485
  ```

- 运行命令：`python3 /home/kvdev/op_test_v2.py 30 3.0`（standalone，复用 `integration-v39` 的 `pcie_contract`；官方 `run_op_test_on_board.py` 仍因 stale-response fail-closed）。

## 5. 操作与边界

- 板卡现留：链路 up、节点齐全、C2H 安静；未宣称 `ATTENTION`/数值/模型质量任何 Gate 通过。
- 未改驱动/DTB/kernel；仅更新 `pcie1-fpga.sh` + `pcie1-fpga.service`（有备份）。
- **每次 FPGA 重配后必须完整恢复**（见 §4），仅 rebind 不够。
- 已记录：新 bit `imx415_pcie_4k.bit` SHA256 `165E2B97…3C9F840F`。
- 待补：`metadata.attention_supported` 仍为 false（`ATTENTION(op=0)` 未实现）。

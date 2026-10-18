# PC2 负例测试计划（READY/FAULT/DONE + SOFT_RESET）

状态：**计划 + 离线 harness 已就绪；真实寄存器/软复位待 B 新 bit。**
目标：在 B 提供 STATUS/CONTROL 后，证明 PC2 不仅能跑正常路径，还能在
未就绪、阻塞、故障和跨进程场景下正确 fail-stop。

## 0. 前置

- B 的新 bit 包含：
  - STATUS：BAR0 + 0xA4（候选）`DONE/ERR/READY/FAULT/BUSY`
  - CONTROL：BAR0 + 0xA8（候选）`SOFT_RESET/SESSION_ABORT`
  - 或 B 最终确认的其他 BAR/偏移
- PC2 配置 `status_config.json` 填真实 `bar_id/status_offset/control_offset/node`。
- 驱动：当前原版无 `ANLOGIC_IOCABORT`；in-flight abort 用例需临时安装
  `/home/kvdev/sgdma_drv_fix/anlogic_pci.ko`，测完恢复原版。
- 板卡独占窗口；开始前确认 PCIe 链路、模块和节点；结束/失败后 recovery。

## 1. 用例与判据

| # | 用例 | 操作 | 通过判据 |
|---|---|---|---|
| N1 | 上电/未就绪 | `status_session.py --probe-only` | READY=0 或定义值；host 不发 H2C |
| N2 | 变 READY | 等待/触发 DDR ready，再 probe | READY=1，FAULT=0 |
| N3 | 写前不 READY | 在未就绪时跑 1 轮；或 mock 强制 READY=0 | 快速拒绝；H2C 写次数 0；不进入 10s 阻塞 |
| N4 | 正常 RESET+30 TEST | `status_session.py --rounds 30` | 30/30；DONE=1；ERR=0；C2H 身份匹配 |
| N5 | 在途阻塞写 abort | `board_fifo_abort_test.sh`（需 abort 驱动） | 阻塞后 abort ioctl 在有限时间内释放；worker `ECANCELED`；记录 monotonic |
| N6 | 连续两个独立进程 | process1 30 TEST；process2 30 TEST；中间不做 PCIe recovery | 两者都 PASS；否则记录失败，不自动 recovery |
| N7 | 软复位 | process1 后写 CONTROL.SOFT_RESET，轮询 READY，再 process2 | process2 PASS；FAULT/DONE 清理正确 |
| N8 | 坏 CRC/seq/layer | 注入坏帧或 stale seq | ERR 对应码/FAULT；host 停止；不读 C2H |
| N9 | DDR ready 丢失 | 运行中触发（B/硬件方式） | FAULT/ERR；host 停止；KV 会话失效 |
| N10 | 旧 DONE/旧帧 | 延迟旧 C2H/旧 status | 不能满足新 seq；host FAULT |

## 2. 离线 harness

```bash
cd pcie_transport/status_adapter_20261018
python -B test_status_adapter.py    # 14 tests
python -B test_status_session.py    # 5 tests
```

覆盖：READY 门控、DONE/ERR、FAULT、软复位、两 session、在途 abort、配置偏移拒绝。

## 3. 真实配置

`status_config.example.json` 的偏移是 `null`，`RealBarStatus` 会拒绝启动；
B 确认后填入真实值：

```json
{
  "bar_id": 0,
  "status_offset": 164,
  "control_offset": 168,
  "node": "/dev/ANLOGIC-PCI0_user",
  "use_ioctl": false,
  "abort_node": "/dev/ANLOGIC-PCI0_h2c_0",
  "ready_timeout_s": 1.0,
  "request_timeout_s": 5.0,
  "abort_grace_s": 5.0
}
```

只读探测：

```bash
python3 status_session.py --config status_config.json --probe-only
```

正常 30 轮（H2C）：

```bash
python3 status_session.py --config status_config.json \
  --binding <board binding>.json --start-seq <confirmed> --rounds 30
```

## 4. 验收记录

每次记录：

- 命令、operator、板卡/kernel/driver/runtime、bit SHA256
- `bar_id/status_offset/control_offset/node`、binding/host hash
- 每个请求的 monotonic 时间、status 值、ERR/FAULT、C2H hash
- abort 用例的 stall 时间、ioctl 返回时间、worker 返回码、dmesg
- 两进程用例是否无需 PCIe recovery
- 失败时保留原始帧/日志，不自动重发追加 KV 的请求，不 CPU/mock fallback

## 5. 判据边界

- READY 预读只覆盖写前状态，**不能**替代在途写的中止试验。
- 在途 abort 是 best-effort；engine 会停，必须 fail-stop + recovery。
- 只有 N1–N10 通过且 B/PC1 审核后，才讨论 `deadline_enforced`/`session_reusable` 是否为 true。
- 不以方案 A 的显式风险接受标志放行 v40。

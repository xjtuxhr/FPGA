# PC2 单层 ATTENTION 上板路线：步骤 1 通过、步骤 2 受阻（2026-04-27）

状态：**步骤 1 ✅ 通过；步骤 2/3 ⛔ 受阻于 B 的 endpoint**。作者：PC2。
开放问题仍以 [UNKNOWNS](../docs/UNKNOWNS.md) 为准。板钟异常，时间戳不作证据。

## 工作项

> 让 PC2 验证单次 RESET + 30 轮 OP_TEST；通过后检查 DDR 初始化、实际 KV 读写，
> 再由 PC1/PC2 做 ATTENTION 单层和连续 token 对拍。

## 步骤 1：单次 RESET + 30 轮 OP_TEST —— ✅ 通过

- 板：`linaro-alip`，kernel `6.1.99 #3`；端点 `21:00.0 [1edb:abcd]`；Gen2 x1。
- bit：`imx415_pcie_4k.bit` SHA256 `165E2B976C38BC1826F0D89B5A53D29910189D8B93CD9D7A40A921A23C9F840F`。
- 驱动：`anlogic_pci` 2020.8.21，`h2c_timeout=10`/`c2h_timeout=10`，`poll_mode=1`。
- 方法：**官方 runner**（`Transport` + `SgdmaDevice` + real binding），clean rebind 后：

  ```bash
  DEST=/home/kvdev/work_pc2_pcie/h2cdeadline_20260427_211835
  cd $DEST
  PYTHONPATH=. python3 -m pcie_transport.tools.run_op_test_on_board \
      --binding pcie_transport/bindings/board_20261011.json --rounds 30 --timeout-s 5.0 \
      --out host/results/op_test_<ts>
  ```

- 结果：`errors=0`，reset `0.839 ms`，round p95 `0.516 ms`、mean `0.359 ms`、min `0.232 ms`、total `10.78 ms`。
- 证据：`$DEST/host/results/op_test_<ts>/{op_test_summary.json,op_test_rounds.csv}`。
- 另：单发 RESET 恰好 1 个 32B ACK、seq 回显、无多余输出（见 RESET_ACK_REGRESSION_20260427.md）。

**结论**：传输层（RESET/OP_TEST，framed v2）在新 bit 上稳定通过。⚠️ `deadline_enforced` 仍为 **false**
（H2C 写最坏上界=驱动 10 s；见 BOARD_VERIFICATION_CHECKLIST_H2C_DEADLINE.md）。

## 步骤 2：DDR 初始化 / 实际 KV 读写 —— ⛔ 受阻于 B

当前 endpoint **无法做这一步**，PC2 侧也没有可读信号：

1. `ATTENTION(op=0)` 未实现 → 没有「H2C QKV → 写 KV 进 DDR → 读历史 → 出输出」的数据通路（`PCIE003_FPGA_REPLY3`、快照 2026-10-11）。
2. **应用 status 字未接**（`pcie_status.v` 未实例化）→ 无法从 control 读 `[0]DONE/[3:1]ERR`，也就没有 DDR-ready / KV 状态可观测。
3. BAR0 寄存器实测是**摄像头例程的地图**：`0x5C=0x56440013`（例程版本号，非 endpoint 版本），其余多为 SGDMA/视频相关；没有文档化的 DDR-ready 或 KV 计数器位。
   （2026-04-27 dump：`0x40=2 0x44=0xf00 0x48=0x870 0x4c=1 0x58/0x64=0x017bb000 0x74=0xc05 0x78=0x17bb00 0x80=1 0x84=0x2001 0x8c=0xf000870 0x90=1 0x98=0x64`；其余 0。）

**需要 B 提供（才能让 PC2 检查 DDR/KV）**：
- 实现 `ATTENTION(op=0)` 数据通路（含 DDR 写 KV / 读历史）。
- 按 `PCIE003_INTERFACE_SPEC.md` §4 **接上 status 字**（control 可读 `[0]DONE/[3:1]ERR`），并给 DDR 初始化/ready 至少一个可读位（放在 status 的保留位或独立寄存器，附地址与位定义）。

## 步骤 3：ATTENTION 单层 / 连续 token 对拍 —— 就绪，等 B

- PC2 侧已就绪：`pcie_transport/tools/run_attention_on_board.py`（RESET + N 个 `ATTENTION` 帧，
  `Transport` 校验 framing，`--golden` 对拍 PC1 参考），helper `attention_vectors.py`，PC 单测 11 个全过。
- 一旦 B 上 `ATTENTION(op=0)`：
  1. 单层：`--layer L --start-position 0 --rounds 1`（先只验 framing）；
  2. 对拍：加 PC1 的 `--golden`（Q/K/V→output 参考），验数值；
  3. 连续 token：`--start-position 0..P` 逐位置，验 KV append + 因果性；接 PC1 host 会合。

## 操作提醒

- **JTAG 重配后链路「假 up」**：必须完整恢复（`rmmod anlogic_pci` + `unbind rk-pcie` + `pcie1-fpga.sh` + `insmod`）才生效。
- 若误发 `ATTENTION`（未实现），端点会挂住（H2C 停止消费），需完整恢复。
- 冷启动已加固（`pcie1-fpga.sh` + service `Restart=on-failure`），重启实测自动 up。

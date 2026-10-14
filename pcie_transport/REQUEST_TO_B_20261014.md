# PC2 → B：单层 ATTENTION / DDR 联调所需（2026-10-14）

背景：新 bit（`imx415_pcie_4k.bit` SHA256 `165E2B97…3C9F840F`）上 `RESET` + `OP_TEST` 30 轮
已 0 错误通过（传输就绪）。下一步要检查 **DDR 初始化 / KV 读写** 并做 **ATTENTION 单层 + 连续 token 对拍**，
但下面几项当前缺失、PC2 无从下手。见 [ATTENTION_BRINGUP_STATUS_20261014.md](ATTENTION_BRINGUP_STATUS_20261014.md)。

## 1. status 字（最关键）
按 `pcie_contract/PCIE003_INTERFACE_SPEC.md` §4 **接上独立 status 字**（`pcie_status` 现未实例化），并给：
- 读它的**确切方式与地址**：control 节点 32-bit pread 的 `offset`（还是 ioctl `ANLOGIC_IOCR` 的 `bar/offaddr`？）；
- 位定义确认：`[0]DONE`、`[3:1]ERR`（`0=OK,1=SEQ_ERR,2=LAYER_ERR,3=CRC_ERR`）、`[31:4]` 保留。

## 2. DDR 初始化可观测
DDR 是否 init 成功，需要一个**可读位**（放 status 保留位或独立寄存器都行），并给地址 + 位定义 +
预期值。否则 PC2 只能从「行为对不对」间接猜，无法在发请求前确认 DDR ready。

## 3. `ATTENTION(op=0)` 语义（用于对拍）
请确认/给出：
- 收到一层请求后：是否**先把当前 token 的 K/V 写入 DDR**，再从 DDR 自读整段历史算 attention？
- 单发一次调用对应的 `position` 语义；连续 token 时 host 是**逐 position、每 position 30 层**串行发（契约如此）；
- 因果：当前 position 可见自己及过去、**不可读未来**；
- 输出 `output[9,64]` fp16 的排布与 scale（与 QKV 同 fp16 LE？）；
- 首版不做帧中途背压（整帧进 FIFO）是否仍成立。

## 4. 已确认
- 传输：单发 RESET 恰好 1 个 32B ACK、seq 回显；OP_TEST 30 轮 0 错误。
- 新 bit SHA256：`165E2B976C38BC1826F0D89B5A53D29910189D8B93CD9D7A40A921A23C9F840F`。

## 5. PC2 侧已就绪（你上板即可测）
- `pcie_transport/tools/run_attention_on_board.py`：RESET + N 个 ATTENTION 帧；`Transport` 校验 framing；
  `--golden` 对拍 PC1 参考。
- `pcie_transport/tools/probe_status.py`：只读 status/DDR-ready 探针（给了 offset 即可读）。
- 提醒：**JTAG 重配后链路「假 up」，需先完整恢复**（rmmod+unbind+PERST+insmod）。

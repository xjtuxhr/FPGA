# DeviceOps 接口契约 与 `pc2_sgdma_bridge.py` 审查清单

状态：**契约已定义；对 PC1 `host/backends/pc2_sgdma_bridge.py` 的逐行审查待收到文件**。日期：2026-10-11。作者：PC2。

## 1. 背景

PC1 已完成 v2 帧级桥接，并请 PC2 审查 `host/backends/pc2_sgdma_bridge.py` 与 PC2 `DeviceOps` 是否完全匹配。
**该文件当前不在仓库任何分支/历史，也不在板上**（已用 `git ls-tree`/`git log --all`、板上 `find /` 核对），因此在 PC1 提供前无法逐行审查。

## 2. PC2 提供的接口（`pcie_transport/sgdma_device.py` → `DeviceOps`）

`pcie_transport/transport.py` 定义的 `DeviceOps`：

| 方法 | 语义（PC2 实现） |
|---|---|
| `write(frame, *, deadline) -> int` | **整帧** `os.write` 到 `h2c_0`；返回写入字节数；**要求 == len(frame)**（短写=错误，不分片、不重试）；被 `_interruptible_deadline` 包住（见 H2C_WRITE_TIMEOUT.md） |
| `notify() -> None` | **no-op**：SGDMA 字符设备写本身就是提交，本 binding 无独立门铃（不是伪造 ACK） |
| `wait_ready(seq, *, deadline) -> bool` | 无应用 status 字；返回 deadline 是否未过（完成由完整 C2H 帧证明），不臆造状态位 |
| `read_exact(count, *, deadline) -> bytes` | 从 `c2h_0` **非阻塞 + `select`** 读满 `count` 字节；超 deadline 抛错 |
| `flush_queues() -> None` | 排空 `c2h_0`（recover 时用） |

上层 `Transport`（`transport.py`）保证：**单请求在途**、seq 严格递增不复用、Attention 必须先有有效 RESET ACK、任一错误进 FAULT 且**不静默重试**。

## 3. 桥接必须匹配的检查点

审查 `pc2_sgdma_bridge.py` 时逐项核对：

1. **整帧写入**：一次写完整帧；短写→错误；不把一帧拆成多次 `write`（会变成多个描述符）。
2. **C2H 读取顺序与长度**：先写 H2C 再读 C2H；读**精确**长度（`OP_TEST`/`ATTENTION`→1184B、`RESET_CACHE`→32B），按帧长而非"读到多少算多少"。
3. **RESET ACK**：`RESET_CACHE` 收到 **32B** ack 且 seq 匹配才认为成功。
4. **单请求在途**：进入设备调用**前**占用请求槽，并发/重入立即拒绝。
5. **出错不重试**：短写/短读/超时/CRC/旧帧 → FAULT + 显式 reset；**不自动重试、不伪造 ACK、不追加 KV**。
6. **不写死 BAR 地址**：只用 binding 里的设备节点；控制寄存器走 `_control` ioctl。
7. **deadline**：写路径按 H2C_WRITE_TIMEOUT.md 的有界机制；读路径 `select` 有界；`metadata().deadline_enforced` 如实。

## 4. 需要的动作

请 PC1 给出 `host/backends/pc2_sgdma_bridge.py`（走 `codex/pcie-*` 分支 PR，或直接给 tarball/路径）。
拿到后 PC2 会逐条对照第 3 节；**若发现接口问题，PC2 走 `codex/pcie-*` 分支提 PR，不直接推 main**。

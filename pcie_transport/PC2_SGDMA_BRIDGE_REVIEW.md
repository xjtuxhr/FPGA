# 审查：PC1 `host/backends/pc2_sgdma_bridge.py` vs PC2 `DeviceOps`

日期：2026-10-11。作者：PC2。被测文件：PC1 `Pc2SgdmaBridge`（v2 帧级桥接，`make_transport(config, options)` 工厂）。
PC 端一致性验证：用 `MockDevice` 直接驱动该桥接（不占板卡）。

## 1. 结论：**完全匹配**（一处需改）

桥接调用 PC2 的 `make_device(binding)`，只做帧级 I/O，**没有**包裹 `pcie_transport.Transport`（避免二次帧/序列），
与 `DeviceOps` 语义一致。逐项核对：

| 检查点 | 桥接行为 | 判定 |
|---|---|---|
| 整帧写入 | 一次 `device.write(frame)`，`written != len` 即 error | ✅ |
| C2H 读取顺序/长度 | 先写 H2C→`notify`→`wait_ready`→读**精确** `count`（reset 32 / 其余 1184） | ✅ |
| RESET ACK | 读 32B 并 `unpack_response(op=RESET_CACHE)` | ✅ |
| 单请求在途 | `threading.Lock(blocking=False)`，重入即拒绝 | ✅ |
| 出错不重试 | 任一异常 → `_faulted=True`，后续拒绝；不 drain/不伪造 ACK | ✅ |
| 不写死 BAR | 仅用 `make_device(binding)` 的节点 | ✅ |
| 响应校验 | `wire.unpack_response(expect_seq/op/layer/position)`（含 CRC/长度/旧帧） | ✅ |
| ATTENTION | 显式拒绝（未实现） | ✅ |
| `close()` | 转发 `device.close()` | ✅ |

本地验证输出（MockDevice）：`reset bytes 32`；`test payload match True`；
`short_write→RuntimeError Short H2C write`；`drop_completion→TimeoutError`；`short_read→TransportError`；`faulted blocks retry: yes`。

## 2. 需改（F1）：`deadline_enforced` 被硬编码为 False

```python
# 现状
deadline_enforced=False,
deadline_limitation="PC2 SgdmaDevice.write uses blocking os.write",
```

问题：PC2 现已提供**有界可中断写**（见 [H2C_WRITE_TIMEOUT](H2C_WRITE_TIMEOUT.md)：`SgdmaDevice.deadline_enforced` 属性 +
主线程 `SIGALRM` 中断阻塞 `os.write`）。桥接硬编码 `False` 会使**能力声明永远落后于 PC2 实际能力**，
实板探针仍会因 `deadline_enforced=false` 不放行——即使 PC2 已修好。

建议改动（PC1 侧，一行）：

```python
    def metadata(self):
        return dict(protocol_version=wire.PROTOCOL_VERSION, wire_dtype=wire.WIRE_DTYPE,
                    max_inflight=1, hardware_transport=self.hardware_transport,
                    binding_verified=self.binding_verified, test_supported=True,
                    attention_supported=False, policy_configured=False,
                    deadline_enforced=bool(getattr(self.device, "deadline_enforced", False)),
                    frame_owner="PC1 owns frames; PC2 DeviceOps transfers the exact frame")
```

即：`deadline_enforced` 由设备属性派生、去掉静态 `deadline_limitation`。
（`attention_supported`/`policy_configured` 仍应保持 `False` 直到真正实现。）

补充：桥接里 `if time.monotonic() >= deadline: raise TimeoutError(...)` 在 PC2 新写路径下成为**冗余二次检查**（无害，可保留）。

## 3. 次要观察（非缺陷）

- **两套 host transport 并存**：PC1 的 `pc2_sgdma_bridge.py` 与 PC2 的 `pcie_transport/host_plugin.py`
  是**同一层的两个实现**，都调 `make_device`。需明确**哪个是正式接入**（建议以 PC1 桥接为准，PC2 plugin 作为备选/交叉验证），避免集成时混淆。
- **options 键名不一致**：PC1 桥接用 `binding_path`，PC2 plugin 用 `binding`。各自 `make_transport` 自洽，接线时注意别串。
- **`close()` 不做 `flush_queues()`**：桥接在 fault 后只拒绝、不 reset，符合"软件路径不 drain"的策略；但实板复用时需要 `RESET_CACHE`（endpoint 侧）——这点在集成时确认。

## 4. 动作

- F1 为**接口问题**：按约定走 `codex/pcie-*` 分支（本审查随 `codex/pcie-transport-hardening` 提交）。
  桥接文件属 PC1，PC1 应用该一行改动即可；PC2 可在拿到仓库内文件后一并提 PR 修改。
- 本审查不声称任何板卡 Gate 通过。

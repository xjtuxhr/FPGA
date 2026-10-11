# PC2 → PC1 交接清单（PCIe transport / endpoint，2026-10-11）

范围：把 PC2 的 `pcie_transport` 交给 PC1 接入；含 **F1 一行改动**（PC1 侧桥接）。
依据：本仓库 `main`。**不代表任何板卡 Gate 通过。**

## 1. PC1 需要拉的文件

**代码依赖**
- `pcie_transport/sgdma_device.py` —— 真实 SGDMA adapter（`make_device(binding)`，含**有界可中断 H2C 写**）
- `pcie_transport/transport.py` —— `DeviceOps` 定义 + `TransportError`（被 sgdma 依赖）
- `pcie_transport/binding.py` —— `Binding`
- `pcie_transport/__init__.py`
- `pcie_transport/bindings/board_20261011.json` —— 实板 binding（节点/BAR/公式）
- （`pcie_contract/` 由 PC1 自持）

**要读的文档（按优先级）**
1. `pcie_transport/PC2_SGDMA_BRIDGE_REVIEW.md` ← 含 **F1**（PC1 桥接要改的一行）
2. `pcie_transport/DEVICEOPS_CONTRACT.md` —— 桥接必须匹配的接口契约
3. `pcie_transport/HANDOFF_RESET_OP_TEST_20261011.md` —— RESET+OP_TEST 交接证据
4. `pcie_transport/H2C_WRITE_TIMEOUT.md` —— 为何现在可以 `deadline_enforced=true`
5. `pcie_transport/PC2_REVIEW_v2_ENDPOINT_RTL.md` —— 对 B 的 v2 endpoint 的审查

**可选**：`pcie_transport/host_plugin.py`（PC2 备选 host transport），`tests/test_host_plugin.py`、`tests/test_sgdma_deadline.py`

**不用给**：`ENDPOINT_STATUS_20261006.md`、`PCIE_BRINGUP_RUNBOOK.md`、`VENDOR_PCIE_REFERENCE.md`

## 2. 接入方式（二选一，建议以 PC1 桥接为准）

**A（推荐）PC1 的 `pc2_sgdma_bridge.py`**：已审查与 `DeviceOps` 完全匹配；`make_transport(config, options)`，
`options = {"binding_path": "pcie_transport/bindings/board_20261011.json"}`。
**只需修 F1**（见下）。

**B PC2 的 `pcie_transport/host_plugin.py`**：`make_transport(config, options)`，
`options = {"binding": "...", "timeout_s": 5.0, "attention_supported": false}`。
`metadata()` 已如实声明 `deadline_enforced`（由设备派生）。

## 3. F1：PC1 桥接需改一行（否则实板探针不放行）

`Pc2SgdmaBridge.metadata()` 里：

```diff
-                    deadline_enforced=False,
-                    deadline_limitation="PC2 SgdmaDevice.write uses blocking os.write",
+                    deadline_enforced=bool(getattr(self.device, "deadline_enforced", False)),
```

原因：PC2 已提供有界可中断写（`SgdmaDevice.deadline_enforced`），桥接硬编码 `False` 会让能力声明永远落后。
`attention_supported`/`policy_configured` 继续 `False` 是对的。

## 4. 能力声明（准确口径）

| 能力 | 状态 |
|---|---|
| `RESET_CACHE` / `OP_TEST` | ✅ 已验证（板上 30 轮 0 错误） |
| `ATTENTION` / KV 写入 / 策略配置 | ❌ 未实现（`metadata` 均 `false`） |
| status 字 | ❌ 未接（B 的 endpoint 尚未实例化 `pcie_status`） |
| `deadline_enforced` | 有界机制生效时 `true`（主线程 + POSIX），否则 `false` |

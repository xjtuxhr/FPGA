# PCIe transport 层（PC2）

状态：**UNBOUND，PC-only**。本目录实现 v2 契约之上的设备 I/O 抽象与 OP_TEST
30 轮串行基准，不打开真实设备、不写 BAR、不宣称任何板卡延迟，直到
`TRANSPORT_BINDING.md` 的 binding 证据完整填入。

协作边界见 [COOPERATION.md](../pcie_contract/COOPERATION.md)：PC2 负责 PCIe
transport/SGDMA 复用/测试 endpoint；不修改 host tensor 语义、模型/数值格式或
系统 runtime。协议常量一律引用 `pcie_contract/contract.py`，本目录不重复定义。

## 文件

- `binding.py`：binding 证据数据结构（对应 TRANSPORT_BINDING.md 表）与 UNBOUND 守卫
- `transport.py`：单在途请求状态机（IDLE→H2C→WAIT→READBACK→CONSUMED / FAULT），
  仅实现 v2 README §7 的**逻辑状态**，不臆造硬件寄存器
- `oracle_test.py`：OP_TEST 30 轮串行基准（每轮不同 counter、逐字节比对、
  min/mean/max/p95），区分 raw/framed profile 标记
- `tests/`：mock 设备与状态机/守卫单测，纯内存，无延迟宣称

## PC 侧运行（不登录板卡）

```powershell
python -B -m unittest pcie_transport.tests.test_transport -v
python -B -m pcie_transport.oracle_test --rounds 30 --mock
```

mock 结果只验证状态机与校验逻辑正确，**不是 Gate 证据**。

## 约束

- 保留 SGDMA 驱动 DMA 完成中断；应用层只轮询逻辑状态，不关 MSI/ASPM、不引入 UIO
- 单请求在途：请求槽在**第一次设备调用前**占用，并发/重入立即拒绝（不污染在途请求）
- Attention 在收到有效 reset ACK 前被拒绝；`recover()` 后重新要求 reset，防止沿用不确定的 KV 状态
- seq 非零递增、session 内不复用；旧帧/旧 DONE 不满足新请求
- 超时为**整个请求一个**有限 monotonic deadline；inf/nan/非正值一律拒绝
- short write/read 不算完成，不擅自分段重发；H2C 写完后显式调用 `notify()`（逻辑门铃，映射由 binding 定义）
- binding 校验集中实现：构造/加载/保存/Transport 入口共用同一规则（协议版本、设备 ID、kind）；mock 与实板 binding 用 `kind` 明确区分，`kind="real"` 额外要求 `evidence_ref`/`bound_driver`/`bars`/`address_formula` 交接证据，缺证据一律拒绝
- binding 未完整前 `transport.py` 拒绝运行（fail closed）

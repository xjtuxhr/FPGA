# PCIe transport 层（PC2）

状态：**UNBOUND，PC-only**。本目录实现 v2 契约之上的设备 I/O 抽象与 OP_TEST
30 轮串行基准，不打开真实设备、不写 BAR、不宣称任何板卡延迟，直到
`TRANSPORT_BINDING.md` 的 binding 证据完整填入。

协作边界见 [COOPERATION.md](../pcie_contract/COOPERATION.md)：PC2 负责 PCIe
transport/SGDMA 复用/测试 endpoint；不修改 host tensor 语义、模型/数值格式或
系统 runtime。协议常量一律引用 `pcie_contract/contract.py`，本目录不重复定义。

## 文件

- `binding.py`：binding 证据数据结构（对应 TRANSPORT_BINDING.md 表）与 UNBOUND 守卫
- `sgdma_device.py`：真实 SGDMA 设备适配骨架（**未绑定**，枚举后按 binding 填；未实现即 fail closed）
- `transport.py`：单在途请求状态机（IDLE→H2C→WAIT→READBACK→CONSUMED / FAULT），
  仅实现 v2 README §7 的**逻辑状态**，不臆造硬件寄存器
- `oracle_test.py`：OP_TEST 30 轮串行基准（每轮不同 counter、逐字节比对、
  min/mean/max/p95），区分 raw/framed profile 标记
- `tools/run_op_test_on_board.py`：**板端** framed v2 30 轮 runner（需完整 real binding + 设备模块，fail closed）
- `tools/fit_dtb_patch.py`：**FIT 感知**的 DTB 补丁（p3 是 FIT 容器，真正的 DTB 在 `/images/fdt`）；分析/提取/打补丁/更新 hash，拒绝签名镜像。PC 已验证
- `tools/probe_enumeration.sh`：板上**只读**枚举取证脚本（改前/改后各跑一次；
  只读契约由 `tests/test_probe_tool.py` 守卫）
- `tools/pcie_roundtrip.py`：**RAW** H2C/C2H 往返与延迟（实测 H2C 1920B×200 OK，
  P50 30.2µs；C2H 待 endpoint）；与 framed v2 的 `run_op_test_on_board.py` 区分
- `tools/smoke_regs.py`：经 `_control` ioctl 读 FPGA 寄存器（冒烟，bar_id/offaddr）
- `ENDPOINT_STATUS_20261006.md`：endpoint/transport 现状与联调入口（给 PC1）
- `tools/run_pcie1_bringup.sh`：串口 root 分析入口（当前**只读**；in-place apply 待下一版）
- `PCIE_BRINGUP_RUNBOOK.md`：打开 `pcie@2a210000` 的维护手册（FIT 感知；含厂商优先路线与回滚）
- `VENDOR_PCIE_REFERENCE.md`：厂商 `AFC03_IMX415_PCIE_X1` 例程制品（endpoint bit / 驱动 / PERST 坑）
- `tests/`：mock 设备与状态机/守卫单测，纯内存，无延迟宣称

## PC 侧运行（不登录板卡）

```powershell
python -B -m unittest pcie_transport.tests.test_transport -v
python -B -m unittest pcie_transport.tests.test_patch_tool -v
python -B -m unittest pcie_transport.tests.test_probe_tool -v
python -B -m unittest pcie_transport.tests.test_op_test_runner -v
python -B -m unittest pcie_transport.tests.test_fit_dtb_patch -v
python -B -m pcie_transport.oracle_test --rounds 30 --mock
```

板端（枚举打通、binding 填好后；需操作者窗口，见 COOPERATION）：

```bash
python3 -B -m pcie_transport.tools.run_op_test_on_board --binding <binding.json> --rounds 30 --out host/results/op_test
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

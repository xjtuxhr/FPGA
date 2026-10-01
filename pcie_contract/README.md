# PCIe 接口契约（草案，待联合评审）

状态：**DRAFT 0.1**，对应 UNKNOWNS PCIE-003（packet/地址/layout/完成标识/序列状态，D21 前冻结）。
本目录是 host（Python）与 FPGA Attention（RTL）之间的**唯一接口事实源**：
两侧代码只能引用这里的常量/JSON，禁止各自硬编码。协议带 magic + version，
任何不匹配必须立即报错（fail closed），与 host 现有 gate 风格一致。

## 文件

- `contract.json`：机器可读常量（RTL 测试台 / 其他语言可 parse）
- `contract.py`：Python 侧实现（纯标准库，与 host 风格一致，无 numpy/torch）

## 已约定（候选值，未冻结）

| 项 | 值 |
|---|---|
| 线上 dtype | FP16 小端（候选边界：RK 发已 RoPE 的 Q/K，COMPUTE_ARCHITECTURE.md §2） |
| H2C 载荷 | Q[576]+K[192]+V[192] FP16 = 1920 B |
| C2H 载荷 | attention output[576] FP16 = 1152 B |
| 头部 | 32 B：magic `KVMX` + version + op + flags + layer + position + seq + payload_len + crc32c |
| 完成机制 | posted write + host 轮询 STATUS 寄存器（禁用中断，第一层优化清单） |
| 每 token 交互 | 30 层串行：H2C → doorbell → 轮询 done → 读 C2H → 下一层 |
| 序列复位 | position==0 的首层前发 OP_RESET_CACHE |
| 错误 | STATUS 寄存器置错误位 + host 校验 seq/crc/version，失败即停，不静默重试 |

## 待定（评审时必须给出决定）

1. 设备节点名：`ANLOGIC-PCI0_*` vs `sgdma0_*`（PCIE-004 实测后定）
2. BAR 访问路径：直接 mmap vs 字符设备 read/write 的 `+0x80000` 偏移语义
3. 寄存器偏移 0x00~0x10 是候选，需与 FPGA RTL 联合确认
4. 头部里 position 用 u32（T≤2048 足够）；未来多序列加 stream_id 字段（预留 flags 位）
5. U/M 量化 KV 的 wire 格式：**不在本契约内**（量化在 FPGA 内部完成，PCIe 只传当前 token 的 FP16 K/V）

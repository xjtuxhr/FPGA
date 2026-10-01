# v1 → v2 工程修正记录

2026-10-01 审查对象：main 的 `8fa746f14b86cb0c420fb6e87ac2237abec2201c`。以下是代码/PC 实验结论，不是实板 PCIe 证据。

| v1 问题 | v2 修正 |
|---|---|
| 函数叫 CRC32C，实际 zlib.crc32 | 正式选 CRC-32/ISO-HDLC；已知答案 CBF43926；覆盖 header(零CRC)+payload |
| 0x4B564D58 小端线上为 XMVK | 固定 KVMX 四字节 4B564D58，小端整数 0x584D564B |
| position=0 每层隐式 reset，且独立空 reset 无法打包 | 删除 reset flag；独立全局 32B RESET/ACK，layer255，空 payload |
| response payload_len=0 仍能通过 | 按 op/方向精确检查长度，拒绝短包/尾随数据 |
| 越界 layer/position、未知 op 能打包 | 编解码两端验证，非零 seq、flags/padding/reserved 全检查 |
| header 不受 CRC 保护 | CRC 覆盖 header 与 payload；仍校验当前请求 tuple |
| Python format/flags 与 JSON 双份定义 | format 从显式连续 JSON layout 生成；flags 全预留零；导入时 schema 自检 |
| 禁用中断表述会影响 SGDMA | 应用完成可轮询；保留 driver DMA 完成中断/同步 |
| 猜测性 BAR/attn_ms 常量易被直接使用 | 删除 codec 中的寄存器常量，binding 未证实保持 UNBOUND |
| 自测只含少数 happy path | 独立 bitwise CRC、固定 hex/SHA golden、非法帧/expectation/格式测试 |

v1 PC 负面测试：零 payload_len、非零 reserved/padding 可接受；layer255/position2048/op99 可打包；layer3/position0 自动 reset；空 reset 被拒绝。新回归覆盖这些签名。

v2 是破坏性修订：删去 `crc32c`、`REG_*`、`CTRL_*` 和猜测性 status bits；Header 字段改名 `crc32`；header/check 需要 direction；response 支持 expect_op。任何已有未合并的 v1 caller/RTL 必须一起更新，不提供静默兼容 shim。

同时核查远端已有 `docs/PCIE_LATENCY_OPTIMIZATION.md` 和 `docs/PLAN_C_VS_RK_ONLY_DECISION.md`：其中延迟预期、ASPM/UIO/IRQ/RT 等均不能直接执行或当事实；真实 Attention RTT 不再额外加 Attention 时间，TEST RTT 才可另加。此轮不改这些独立文档，执行边界以本目录和 PLAN 为准。

协议代码、golden 和协作流程修正不关闭 PCIE-001～005、NUM-001、KV-008。FP16 test profile、RK RoPE/head-major 是集成约定，生产数值与真实 endpoint 仍需 reference/实板验证。

## 本次实际验证

2026-10-01，Windows PC：`python pcie_contract/contract.py` PASS；`python -m unittest pcie_contract.test_contract -v` 22 项 PASS，包含 6 份固定 golden、独立 bitwise IEEE CRC、30 次纯 codec 往返和负面用例。测试仅使用标准库，没有开发板访问，不记录或宣称硬件 latency。Git 提交前另运行 `git diff --check`。

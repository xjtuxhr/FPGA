# PCIe 契约与协作入口

更新：2026-10-01。**协作规则已确定；软件测试协议 v2 已确定；实板 transport 和生产数值格式未验证。**

先读 [最终协作规则](COOPERATION.md)，再读本页。机器可读协议只有 [contract.json](contract.json) 一份；[contract.py](contract.py) 是纯标准库 PC codec，不访问开发板。本目录不是 PCIe driver，也不代表 Gate 已通过。

## 1. 现在可以做什么

- PC1：继续当前 NPU Q 重复 Gate，负责 host/NPU/reference/scheduler。
- PC2：修正/复用官方 SGDMA 路径，准备已知 pattern 的双向小包测试；不先实现完整 Attention。
- 两人可以同时 SSH、编辑、做 PC 测试。**板上硬件实验串行**，开始前确认另一方空闲，结束后释放；目录和分支独立。
- main 只收 review 后的相关变更，不覆盖别人文件；接口改动必须同步 JSON、codec、golden、测试。
- 根目录 [AGENTS.md](../AGENTS.md) 要求后续 Codex 先读取并遵守上述规则。

## 2. 已确定与未验证的边界

| 等级 | 内容 |
|---|---|
| 项目冻结 | 方案 C、SmolLM-135M；RK 做主要 linear，FPGA 做 KV/KVmix/Attention |
| 协作决定 | 独立目录/分支、单板单硬件实验、系统级操作先确认、版本化交接 |
| 固定测试协议 | 下述 v2 header、CRC32、独立 reset、单请求在途、OP_TEST oracle |
| 待实测 | 节点、BDF/BAR、AXI-MM/AXI-ST、DMA 对齐/长度、完成通知、延迟 |
| 待数值 Gate | 生产 QKV/output dtype/scale、RoPE 数值与 Attention 算术；测试 FP16 不提前冻结这些 |

开放问题的唯一清单仍是 [UNKNOWNS](../docs/UNKNOWNS.md) 的 PCIE-001～005、NUM-001、KV-008。本目录不复制另一套清单。

**v1 不兼容、不得继续使用。** v2 修改 magic、CRC 覆盖和 reset 语义并移除猜测性寄存器常量。任何版本不一致立即失败，不进行兼容猜测。

## 3. 模型与 tensor 语义

Smol135M：30 层，hidden=576，Q/KV heads=9/3，head_dim=64。首版 context=64/128/256，模型上限 2048。

```text
RK embedding/norm/NPU QKV → RK RoPE(Q/K) → backend serialization
→ FPGA 当前 token 的 Q/K/V → KV append/quant/dequant → QK/softmax/PV
→ attention_output → backend deserialization → RK O/MLP/下一层
```

集成约定：RK 在送出前对 Q/K 执行模型兼容 RoPE，V 不旋转；使用 Smol/HF 的 rotate_half 半区配对，不把维度重排误作相邻偶奇配对。head-major、每 head 的 64 项连续；Q[9,64]、K/V[3,64]，顺序 Q→K→V，输出[9,64]；GQA 为 `kv_head = q_head // 3`。真实 RoPE/数值必须用 reference 验证，不以协议字段代替验证。

host 的软件 Tensor 可继续 F32。FP16 打包/解包只在 FPGA backend 内，NPU INT32 output 的 scale/dequant 必须先完成，不能把 INT32 buffer 直接当 FP16。正式接入要拒绝 NaN/Inf/溢出；`pack_f16/unpack_f16` 提供基础检查。

当前 PC1 本地软件接口为 `reset()`、`run_attention(layer, position, q, k, v) -> Tensor`；Q/K/V 软件向量为 F32[576]/F32[192]/F32[192]，返回 F32[576]，描述符带 layer/position。这些 host 文件目前尚未发布 main；集成前必须交接源码版本，不能只凭 README 认定已收到可运行 host。PCIe codec 不依赖 host，可以先独立测试。

B=FP16 KV storage；U=全 token K2/V2 无 tail；M=混合层精度+recent tail。**三者共用相同 wire profile**，KV 量化在 FPGA；不下发压缩历史 KV 或模型权重。策略配置属于独立 setup control plane，尚未实现；正式 Attention 前必须确认配置已完成，不默认猜测 B/U/M。

## 4. 测试 profile：尺寸与帧

FP16 little-endian 测试 profile（生产精度仍待 NUM-001）：

| 操作 | H2C payload | C2H payload | 含 header 的逻辑帧 |
|---|---:|---:|---|
| ATTENTION=0 | Q576+K192+V192：1920B | output576：1152B | 1952B / 1184B |
| RESET_CACHE=1 | 0B | 0B ack | 32B / 32B |
| TEST=2 | 1920B 已知 pattern | 输入前 1152B | 1952B / 1184B |

32B header 逐字段偏移见 JSON。线上 magic 字节固定为 `4B 56 4D 58`（KVMX），小端 u32 是 `0x584D564B`；version=2。

所有 flags、padding 和 reserved **必须为 0**。没有隐式 reset、last_layer 或 stream_id；当前只支持一个 generation session 和一个在途请求。layer=0..29、position=0..2047；reset 专用 layer=255、position=0。seq 为非零 u32，包含 reset 在内每次请求递增，响应原样回显；不能在同 session 内回绕或复用 seq。

header 检查：magic、version、op、flags、layer、position、seq、方向相关的精确 payload_len、保留字节、实际帧长度、CRC 全部通过才能使用。C2H 还必须匹配**当前在途请求**的 op/seq/layer/position；旧 DONE/旧帧不能算完成。

## 5. CRC 决定

采用 **CRC-32/ISO-HDLC（IEEE）**，不用 CRC32C/Castagnoli，避免双方使用不同算法。参数与已知答案在 JSON：

```text
poly       0x04C11DB7（反射 0xEDB88320）
init/xor   0xFFFFFFFF / 0xFFFFFFFF
reflect    input=true, output=true
123456789  → CBF43926
```

覆盖：完整 32B header（crc32 字段临时置零）+逻辑 payload。reserved/padding 的零值也参与 CRC；**不包含 transport 外部 DMA padding**。CRC 数值按小端写入 offset=24。RESET 空 payload 也校验 header，不把 CRC 设成空串的 CRC。

## 6. Reset 与序列状态

```text
setup policy/numeric configuration（另行验证）
→ RESET_CACHE(seq, layer=255, position=0, empty)
→ 收到同 seq/op 的有效 32B ack，确认所有层缓存和长度已清零
→ token position=0：layer0 → ... → layer29
→ position=1：layer0 → ... → layer29
→ ...
```

RESET 不重置 transport seq；每个新 prompt 开始只进行一次全局 reset。任何 Attention `position=0` 都不触发隐式 reset。

真实 endpoint 必须保证每层 KV position 连续；同位置不能重复追加，失序/重复请求报错且不再次计算。host 先完成一个 position 的全部层，再开始下一个 position。新 K/V 追加后，当前 position 可以看见自己及过去，不能读取未来 KV。

请求/响应错误、超时、CRC/状态不符立即进入 FAULT，停止后续层，不静默重试。KV 可能已被修改；恢复需双方显式确认，清理/隔离旧收发队列并重新 reset，不能将下一次读到的旧 response 当新结果。

## 7. Transport 状态：逻辑完成不等于 DMA 完成

第一版复用官方 SGDMA H2C/C2H 字符设备；控制优先使用**验证过的 user 字符设备 32 位 pread/pwrite**，不默认 raw mmap。具体节点/地址必须填入 [transport binding](TRANSPORT_BINDING.md) 并留实板证据。

```text
IDLE
→ 准备/按 binding 挂好接收（AXI-ST 可能需要先准备 C2H）
→ 完整 H2C 传输/可见性确认
→ ACCEPTED/BUSY（必要的通知由 binding 实现）
→ RESULT_READY（若有应用状态寄存器，轮询匹配 seq 的状态）
→ C2H 完整读回、driver 同步完成
→ 长度/CRC/seq/tensor 校验 → CONSUMED → IDLE
任一错误 → FAULT
```

这些是**逻辑状态，不是已经存在的硬件寄存器**。ACK/清 DONE/结果消费、通知顺序与地址由 binding 对应实际 endpoint；不得照此臆造 BAR map。AXI-ST 与 AXI-MM 的帧界定、TLAST/TKEEP、背压和启动顺序也要验证。

- 保留官方 driver 的 DMA 完成中断/同步；应用轮询 Attention 完成不关闭 MSI/driver IRQ。
- PCIe posted write 不等于 payload 已被 endpoint 接受；按实际 driver/endpoint 完成规则再通知。
- 所有等待必须有明确有限 deadline；driver 阻塞超时也需核对，不能只给外层 Python 加 timeout 就宣称可靠取消。
- short read/write 不当作完成。能否续传由 channel 的帧语义决定；禁止未经验证地切碎帧重写。
- 控制 read/write 每次仅 32bit；不能用 control 节点写整帧。user 节点的 `+0x80000` 与 raw BAR offset 不是同一地址语义。

## 8. PCIe 第一阶段验收

先测官方数据通路的原始 1920B/1152B；如果已有 test endpoint 支持 v2，再测带 header 的 1952B/1184B。原始 transport 测试和 framed 测试必须分别标记，不能混报。

固定 TEST oracle：输入前 4B 是小端 counter，其余 `byte[i]=(counter+i)&255`；返回输入前 1152B。**只验证 transport，不执行 Attention、不改变 KV。** 真实 echo 1920B 是另一种 smoke test，不能算已经验收 1152B 响应。

至少 30 次串行 request/response，每轮不同 counter，完整逐字节比较，错误数必须为 0。记录 min/mean/max/p95、30轮总时间、提交/等待/同步及 dtype/binding/版本/hash；不拿 PC mock latency 或纯 DMA API 时间冒充整层往返。

DMA padding、buffer 对齐、传输粒度和设备地址单列记录，不加进 logical payload_len 或 CRC，也不擅自重复 frame 填充。每层 profile 3072B payload、含 header 3136B；30层 94080B/token≈91.875KiB，不含 transport padding。

旧 `docs/PCIE_LATENCY_OPTIMIZATION.md` 只是候选思路，不是板上操作清单；其“现状/预期延迟”不是实测值。不得据此先关闭中断、改 ASPM/实时调度或引入 UIO/VFIO。30轮用于最小稳定性 Gate，不能据此宣称可靠 P99。

计时避免重复：TEST transport RTT 不含真实 Attention，可在估算中另加 Attention；真实 Attention request→response RTT 已含 FPGA 计算，**不能再加一次 Attention 时间**。RK-only 质量/数值一致性也要另验证，RKLLM 整模型 smoke test 不能直接当同配置性能基线。

## 9. PC 验证与交接文件

从仓库根目录运行（PC，不登录板卡）：

```bash
python pcie_contract/contract.py
python -m unittest pcie_contract.test_contract -v
```

通过仅说明 codec/golden/非法帧处理正确。RTL/C/C++ 必须消费同一 JSON/golden 并逐字节对拍，**不能因 Python self-test PASS 就关闭 PCIe Gate**。

- [golden_vectors.json](golden_vectors.json)：固定 header hex、payload 生成方式、整帧 SHA256。
- [test_contract.py](test_contract.py)：正负用例及独立 bitwise CRC 对照。
- [TRANSPORT_BINDING.md](TRANSPORT_BINDING.md)：实板绑定需要记录什么，不包含猜测性 BAR 值。
- [COOPERATION.md](COOPERATION.md)：负责人、Git、共享板卡与证据规范。
- [REVIEW.md](REVIEW.md)：v1 问题与 v2 修正，避免回归。

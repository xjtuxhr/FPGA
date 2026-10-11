# PC2 审查：B 的 v2 endpoint RTL vs 契约 v2

日期：2026-10-11。审查对象：`origin/codex/fpga-kv-attention@df17507` 的 `fpga_kv_attention/rtl/{v2_endpoint,crc32_ref,pcie_status,axis_fifo,usr_loopback}.v`。
依据：`pcie_contract/contract.json` / `contract.py`（v2）。**这是 PC 侧静态审查，不是板卡 Gate 证据。**

## 1. 结论：核心帧处理正确，但有 5 处需修/确认

以下**已验证正确**（与契约一致）：

| 项 | 证据 |
|---|---|
| 请求头字段偏移 | `v2_endpoint.v:92-94,111-112`：op@byte6、layer@byte8、position@byte12-15、seq@byte16-19、crc@byte24-27 ✅ |
| 响应头布局 | `:62-63` `resp_hdr0/hdr1` 与 contract `header_layout` 逐字节一致 ✅ |
| CRC 算法/覆盖（响应） | `crc32_ref.v` = zlib.crc32（`0xEDB88320`+xorout）；响应 CRC 覆盖"清空 crc 的响应头 + 1152B"（`:97-100,116-118,133-134`）✅ |
| RESET → 32B ack | `:120,158-159`：op=RESET 跳 payload，hdr1 置 tlast ✅ |
| TEST → 回显前 1152B | `:129-135,162-170` 经 FIFO 回显 72 拍 ✅ |
| tkeep 全 1 / tuser 0 | `:146-147,156-157,166-167` ✅ |
| 单请求在途 | 忙碌期 `tready` 拉低（`:69`），结构上单帧 ✅ |

## 2. 问题

**F1（重要）：请求 CRC 只算不校验。**
`v2_endpoint.v:35-44` 例化 `crc32_ref` 算出 `req_crc`，但 **`req_crc` 从未与锁存的 `req_crc_field` 比较**（`:112` 锁存后即为死信号），也不产生任何错误。→ **坏 CRC 的帧会被照常处理**。契约要求"CRC 全部通过才能使用"（README §4/C 节）。建议：比较 `req_crc` 与 `req_crc_field`，不符则置 `CRC_ERR`/丢弃。

**F2：不校验 magic / version / flags / padding / reserved。**
`S_H0` 只取 op/layer/position（`:92-94`），未检查 `tdata[31:0]==MAGIC`、`tdata[47:32]==2`、flags=0、padding/reserved=0。契约要求逐项检查，否则任意垃圾帧会被当合法帧。

**F3：无 seq/position 连续性校验，status 字未接。**
契约 C4 要求"position 连续、重复/失序报错不重算"。RTL 仅锁存 `position_r/seq_r`，无连续性判断、无错误输出。`pcie_status.v` 存在但 **`v2_endpoint.v` 未实例化**，所以 status 字（`[0]DONE/[3:1]ERR`）没有连到 endpoint —— 与 B 自己在 `PCIE003_FPGA_REPLY3` 里"status 未接"的说法一致。

**F4：ATTENTION 路径与注释/声明不符（潜在挂死）。**
`v2_endpoint.v:120`：`state <= (op_r==OP_RESET) ? S_TX0 : S_PAY;`。对 `op=0`(ATTENTION) 会**当普通帧吃掉 120 拍**，`resp_payload_len=1152`（`:61`，因为 op≠RESET），`hdr1.tlast=0`（`:158`），随后 `S_TXP` 从**空 FIFO** 读（`:162-170`，op≠TEST 未写 FIFO）→ **永远等不到 `fifo_rd_valid`，挂死**，**不会**如注释所说"回 32B ack 占位"。未知 op（≥3）同理。
当前 host 侧显式拒绝 ATTENTION，暂不触发；但实现与声明不一致，且未知 op 无拒绝路径。

**F5（需核对，可能编译/综合报错）：`axis_fifo` 端口/参数不一致。**
`axis_fifo.v:9` 只声明 `DEPTH, DATA_W, ADDR_W`，端口无 `s_keep`/`m_keep`；
但 `v2_endpoint.v:53` 与 `usr_loopback.v:28` 例化时用了 `.KEEP_W(16)`、`.s_keep(...)`、`.m_keep(...)`；
而 `axis_fifo_tb.v:12` 又**不用** KEEP。
三者不一致。若 iverilog 把未知端口当错误，则 v2_endpoint/usr_loopback 的仿真用的应是**另一版带 KEEP 的 FIFO**；提交进仓库的这版 FIFO 与它们**不匹配**，TD 综合可能直接报错。需统一（FIFO 加 KEEP，或例化去掉 KEEP）。

## 3. 测试覆盖缺口（B 的 `v2_endpoint_tb` + `gen_v2_endpoint_vectors.py`）

只覆盖 **3×TEST + 1×RESET 的正常帧**；**未覆盖**：坏 CRC、坏 magic/version、错 seq、短/长帧、未知 op、ATTENTION。因此 F1/F2/F4 不会被现有仿真发现（合法帧才喂进去）。

## 4. 对 PC2/host 路径的影响

- **不影响**当前 OP_TEST 正确性：响应头/响应 CRC 由 host（桥接/transport）用 `contract` 校验，且已在板上 30 轮通过——说明**响应生成正确**。
- **影响**健壮性/契约完整性：endpoint 不校验请求 CRC/magic，也不做 seq 连续性/错误上报；这些是 `TRANSPORT_BINDING` 里"完成/错误语义"与 PC1 桥接预期（status 字、SEQ_ERR/CRC_ERR）尚未闭环的部分。
- F1/F2 修好后，`TRANSPORT_BINDING` 的 CRC/seq 语义才算真正端到端成立。

## 5. 建议给 B

1. 修 F1（请求 CRC 比较 + CRC_ERR）、F2（magic/version/flags/padding 校验）。
2. 修 F5（统一 `axis_fifo` 的 KEEP 端口），否则 v2_endpoint 综合可能不过。
3. F3/F4：接 `pcie_status`、补 seq/position 连续性 + 未知 op/ATTENTION 的显式 ack 或错误（避免空 FIFO 挂死）。
4. 扩 `v2_endpoint_tb` 负例（坏 CRC/magic/seq/长度、ATTENTION）。

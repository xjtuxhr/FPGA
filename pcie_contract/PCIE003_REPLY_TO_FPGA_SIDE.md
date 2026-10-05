# 给 FPGA 侧（B）的回复与澄清清单（PCIE-003，关联 NUM-001 / KV-002）

> 来自：PC2（PCIe transport / endpoint）。回复 `pcie_interface_requirements.md`。
> 立场：**沿用既有 `pcie_contract/contract.json` v2，不另起炉灶**；先打通 PCIe 枚举与原始链路，再冻结 packet/BAR/FIFO。
> 说明：以下 `Q` 是请 B 逐条确认/回答的问题；`A(PC2)` 是 PC2 已给的约定。

## 0. 总体结论

1. `A(PC2)` 采纳 B 的倾向：**沿用 contract.json 版本机制**。
2. `A(PC2)` 线上测试 profile 为 **FP16 little-endian**；生产 QKV/output 的 dtype/scale/layout 属 **NUM-001**，由 PC1 定，未冻结前不写死。
3. 现状：RK3576 的 **PCIe 控制器在 DTB 里是 `disabled`**，端点尚未枚举（无 `/dev/ANLOGIC*`、`/dev/sgdma*`）；已备好一次维护（改 `pcie@2a210000` → `okay` + 重启）打通链路。**BAR/FIFO 只能等枚举后按实板 SGDMA 路径填**，现在不猜。

## 1. 契约 v2 关键约定（请 B 按此对齐）

- 帧：**32B header + payload**；线上 magic `4B 56 4D 58`（KVMX），`version=2`。
- 校验：**CRC-32/ISO-HDLC（IEEE）**，覆盖 header（crc 字段置零）+ 逻辑 payload；已知答案 `123456789 → CBF43926`。
- op：`RESET_CACHE`(空 payload, layer=255) / `ATTENTION` / `TEST`。
- `ATTENTION`：H2C = **Q576 + K192 + V192** FP16 = **1920B**；C2H = **output576** FP16 = **1152B**（不含 32B header/DMA padding）。
- 元数据：`layer=0..29`、`position=0..2047`；`seq` 非零递增、响应原样回显；**单请求在途**；无隐式 reset。
- 排序约定：head-major，每 head 64 项连续；`Q[9,64] → K[3,64] → V[3,64]`；GQA `kv_head = q_head // 3`。

## 2. 必须澄清的冲突（最高优先）

**C1 — K/V 上链到底传多少？（契约 vs 需求矛盾）**
- 契约/方案 C：host 每层只发**当前 token** 的 `K/V[3,64]`（各 192B），KV 历史**存在 FPGA DDR、由 FPGA 自读**。
- 但 `pcie_interface_requirements.md` 写 K=`3×T×64`、V=`3×T×64`（**整段历史**）。
- `Q`：B 要的是哪种？若是"全历史上链"，会与"KV 存 FPGA DDR"和 90KiB/token 的载荷推导直接冲突，每层载荷会暴涨。
- `Q`：`attention_b_top` 的 K/V 端口是**FPGA 内部（从 DDR 读）**，还是**要 PCIe 每层灌全历史**？两者接口完全不同。

**C2 — attention 输出 dtype/位宽**
- 契约 C2H = **576×FP16 = 1152B**；需求写 `out[31:0]`（**每元素 32bit**）。
- `Q`：线上是 16bit 还是 32bit？若 32bit，是 Q16.16/F32 还是别的？scale/layout 是什么？（与 NUM-001 一起定）

**C3 — `start`/`done` 与契约映射**
- 契约用 `seq`/`DONE`/`RESET` 语义，没有独立 `start`；需求要 `start` 脉冲和 `done` 脉冲（**RTL 还没加**）。
- `Q`：`done` 是"FPGA 逻辑算完"还是"含 C2H 到 host 的同步"？建议 `done` 仅表逻辑完成，C2H/校验由 transport 侧按 binding 完成。
- `Q`：`start` 是否等价于收到本层请求的第一拍？可否用 header 的 `layer/position/seq` 代替，不引入新握手线？

**C4 — 层状态归属**
- 契约要求：host 顺序发，FPGA 保证**每层 position 连续**、同位置不重复追加、不读未来 KV；失序/重复报错且不重算。
- `Q`：`position` 由 header 给还是 FPGA 自增？重复/失序时 FPGA 的响应是什么（error 码/状态）？

**C5 — BAR / 寄存器 / FIFO**（依赖枚举）
- `A(PC2)`：优先沿用官方 **SGDMA 字符设备**（H2C/C2H + 4B control pread/pwrite），保留官方 DMA 完成中断；应用层只轮询逻辑 DONE。地址公式/BAR 由实板枚举后写入 `TRANSPORT_BINDING.md`。
- `Q`：请 B 提供 **FPGA 侧收/发 FIFO 深度**、是否 AXI-ST（`TLAST/TKEEP`、背压）还是 AXI-MM，以及背压时会否阻塞 H2C/notification。

## 3. 请 B 补充的参数（供 PC2 写 spec）

1. 每层输入/输出**字节数与分包数**；Q/K/V 是各一个流还是合并；若 K/V 只发当前 token，FPGA 从 DDR 读历史 + 计算的**时序预算**。
2. `out` 元素的**吞吐/时序**；在 Fmax 88.9MHz、T=256 下每层 attention 的**估算周期/时间**。
3. 是否有 **status/error 寄存器**（供 DONE/错误确认），还是纯流式。
4. FPGA 侧 **FIFO 深度**与流控约定。
5. 是否有**性能计数器**（可后续接入 uint64/cycle，频率/回绕需记录）。

## 4. 关联但非 PC2 负责（已转对口）

- **KV-002 / NUM-001**（定点格式 Q8.8 / Q0.8 / Q0.16 / Q16.16、group 轴 K按channel/V按token、K3 打包、PCIe dtype）：由 **PC1** 回复。
- **DDR-001/002**（用户侧位宽/burst/延迟/并发读写/最小 pattern 校验例程）：由 **FPGA 老师**回复。

## 5. 建议对接顺序（里程碑）

1. 打通 PCIe 枚举 → 原始 **1920B/1152B** 双向链路可用（D7 初证据）。
2. 带 32B header 的 framed v2：OP_TEST 30 轮串行、0 错误、记 P50/P99（D14）。
3. 再接**单层** ATTENTION（先 B/FP16 profile），确认 C1/C2 后扩大。
4. 全程 **同 NPU 权重、同 B/U/M、同 generation 配置**；失败即停，不静默 CPU fallback、不静默追加 KV。

---

请 B 按 `C1–C5`、`Q` 逐条回复；确认后 PC2 出 `PCIE-003` 接口 spec 草案，与 `contract.json` 同步（JSON/codec/golden/测试一起改）。

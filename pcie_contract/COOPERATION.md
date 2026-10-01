# 两台 PC 的最终协作规则

状态：**协作规则已确定**。适用于成员、老师和后续 Codex；不代表 NPU/PCIe Gate 已通过。

## 1. 分工与共享边界

| 负责人 | 主责 | 不能单方面改变 |
|---|---|---|
| PC1 | RK host、NPU Gate、CPU reference、数值转换、模型 scheduler | FPGA 边界、协议版本、B/U/M 定义 |
| PC2 | PCIe transport、官方 SGDMA 驱动复用、测试 endpoint、FPGA Attention 接入 | host tensor 语义、模型/数值格式、系统 runtime |
| 双方 | 接口测试向量、集成、实验记录；PC1 汇总接口变更并合并 main | 方案 C、Smol135M、实验公平性边界 |

PC1 `192.168.138.1 → end1 192.168.138.101`；PC2 `192.168.137.1 → end0 192.168.137.101`。两条 SSH 连接进入**同一台 RK3576**，共享 Linux、NPU、内存、PCIe、FPGA 和文件系统。两个网口不是资源隔离。

允许继续共用 `kvdev`，不为协作另行改账户/权限。板上分别用 `/home/kvdev/work_pc1_npu/` 与 `/home/kvdev/work_pc2_pcie/`；每次新包解到新子目录，结果不覆盖。禁止覆盖对方源码、清理对方结果、在对方目录执行 git pull/reset；只能停止自己确认过 PID 的进程，禁止笼统 pkill/python 或 killall。

## 2. Git 和接口版本

- PC1 使用 `codex/rk-host-*`；PC2 使用 `codex/pcie-*`。各自 PC 的 clone/工作目录独立。
- 通过 PR 提交到 main，由另一方检查接口与测试后，PC1 集成。不得 force-push main；存在并发提交时重新对齐，不覆盖对方提交。
- 本次经用户明确批准的契约修订可作为一次直接 main 提交；之后回到上述 PR 流程。后续 Codex 的提交/推送/发消息仍需用户授权，不能以本规则代替授权。
- 仅提交本次范围内源码、文档、轻量 golden 和测试；不默认上传模型、SDK 二进制、系统镜像、测试包或个人结果。不得使用 `git add .` 收入无关改动。
- 每次交接写出 commit、契约版本、文件清单/hash 和测试命令。GitHub 上没有的本地 host 代码不得声称已同步。原子接口变更必须同时更新 JSON、codec、测试与 golden；不留半套版本。
- 不同协议版本立即拒绝。测试协议可冻结；生产数值格式和 transport binding 只能在对应实测证据后冻结。

## 3. 板卡操作与测试互斥

**板卡只能有一个硬件实验负责人。** PC 上编辑、mock/unit test 可并行；板上 NPU、PCIe/DMA、FPGA 测试和板上编译都按时间窗口串行，避免相互干扰和污染计时。

开始前告诉另一方：实验、目录/commit、预计占用、是否有系统副作用；获得“板卡空闲”确认后再运行，结束/失败都通知释放。暂时不以自动锁替代这个确认；双方手工操作也必须遵守。

重启、FPGA 重配置、加载/卸载驱动、PCIe rebind/rescan、写 BAR、改变网络/权限/频率、替换 runtime、修改 DTB/kernel/镜像，必须明确列出目标、副作用和恢复方法，并得到板卡操作者及另一方批准。不能把官方一键脚本当只读工具。

批准针对一组范围清楚的实验；其内已验证地址的正常控制读写不需逐次重复批准。越出该范围、改变 mapping/系统或发生异常则停止并重新确认。

保留 SGDMA 驱动已有 DMA 完成中断。应用层轮询 Attention DONE **不是**关闭 MSI/驱动中断。不得修改 `/usr/lib/librknnrt.so` 等系统库来解决单个程序问题。

Codex 默认遵循 Human-in-the-loop：先 PC 测试，实板由用户执行一组明确命令并返回完整日志；没有操作与日志不得宣称 Gate 通过。失败即停，不能偷偷 CPU fallback、绕过 FPGA 或静默重试追加 KV。

## 4. 证据和接入门槛

- 每次记录：执行身份、板卡/kernel/driver/runtime、源码及 bitstream hash、binding、输入/reference、stdout/stderr、正确性、计时边界、重复次数和错误数。板上墙钟不准时同时记录 PC 接收时间。
- NPU 与 PCIe Gate 分开通过，不互相替代。NPU 先完成当前 Q 重复 gate；PCIe 再单独测已知 pattern 的 1920B 下发/1152B 返回，至少 30 个串行往返。真实协议测试另计 32B header 和 DMA padding。
- 延迟记录 min/mean/max/p95、30 轮总时间，包含提交、通知、等待、读回与校验；另行计 codec/设备内核时间，不能把两者重复相加。
- `OP_TEST` 不执行 Attention、不追加 KV。它通过不代表真实 Attention 或整体方案 C 已通过。
- 两个 Gate 有最小实板证据后，只接一层；之后按项目既定逐级集成顺序扩大。
- 开放问题只在 `docs/UNKNOWNS.md` 维护；本目录记录协议/合作决定和 transport 证据入口，不复制第二份独立 UNKNOWN 清单。

## 5. 后续 Codex 必须执行

开始 host/PCIe/FPGA 工作先读本规则与 `README.md`；保留未提交文件；检查对方提交和实际接口版本；未授权不访问共享板卡、不改系统、不推送。不能因本契约存在便关闭 PCIE-001～005、NUM-001 或 KV-008。

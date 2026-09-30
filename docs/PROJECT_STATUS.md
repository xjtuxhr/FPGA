# 当前项目状态

更新：2026-09-30。[PLAN](../PLAN.md)定义边界，[架构](COMPUTE_ARCHITECTURE.md)定义数据流，[RK3576 Linux 开发入口](RK3576_LINUX_DEVELOPMENT.md)沉淀随板教程与操作 SOP，[UNKNOWNS](UNKNOWNS.md)是唯一开放问题清单。

## FROZEN：团队决定

正式模型HuggingFaceTB/SmolLM-135M；方案C。RK CPU/NPU负责weight-heavy，PH1A90负责KVmix/Attention。权重常驻RK LPDDR4X；FPGA DDR存KV/metadata/buffers；不走PCIe权重流送。目标不用disRAM，尚未综合验证。

B=FP16 KV storage；U=全层全token K2/V2无tail；M=layer-aware mixed + recent FP16 tail。固定RK路径/权重/PCIe格式/FPGA算术/评测配置。PC离线分析层重要性。

## FACT：证据已存在

- 本地config/header：30层、D576、FFN1536、Q/KV9/3、HD64、vocab49152，134,515,008参数，tied embedding，checkpoint实际F32；hash见 [模型证据](MODEL_AND_PC_RESULTS.md)。正式制品签核/PC一致性尚未完成。
- PC报告Smol B/U/M PPL约19.76/23.90/22.64（Wikitext2），支持软件动机，不证明NPU/FPGA路径质量。
- SEG324名义240DSP、272ERAM块/680KiB口径；disRAM单独计。RK 4GB LPDDR4X与FPGA 256MiB DDR是独立域，实物版本/BOM需核对。
- learningresources有RKNN/RKLLM样例、Linux镜像、PCIe SGDMA驱动/工程；存在不等于已跑通分层Smol。
- 已静态核查入门 Linux、系统/设备/驱动、RKNN/RKLL、PCIe 与 Wechat_ref 相关资料：厂带 Buildroot 通常无需刷；异构 Debian 1.2.1 镜像、PCIe 工程与 SGDMA 源码在本地。RKLLM整模型接口未查到逐层外部 Attention；PCIe 视频示例的 H2C 并非现成 QKV 消费者。教程/源码冲突与限制见上述开发入口。
- **实板观察（成员于2026-09-30提供终端输出）**：`/etc/os-release` 显示 Debian 12 bookworm，串口 shell 可用；`end0` 已临时设为 `192.168.137.101/24`，PC Realtek“以太网”为 `192.168.137.1/24`。`sshd` 监听22端口，成员已用 `kvdev` 经 MobaXterm SSH 登录。`root` 密码锁定且 SSH 禁止 root 密码登录。精确镜像版本、kernel、网络/SSH重启后状态和文件传输仍未验证。

## DERIVED / CANDIDATE，不是MEASURED

脚本linear_macs/attention_macs：RK linear134.479872M MAC/token，FPGA QK+PV=34,560T，T256为8.84736M；LM Head28.311552M在RK侧。
16bit PCIe候选每token90KiB、30次层交互；ERAM140+64=204KiB为候选。
T256 B/U/M KV=5.625/1.054688/1.672119MiB（group32、tail32、重要层3、metadata4B、dense K3），加1MiB buffer后容量通过。

## 进度与阻塞

RK3576 基础串口与 SSH 登录已完成，恢复步骤见 [启动清单](../STARTUP_CHECKLIST.md)。尚无 NPU真实shape benchmark、PCIe小包往返、Attention综合或完整Smol生成证据。供应商 SDK 1.1.0 包/预制 VM 未在本地找到，实际镜像/内核与 NPU/PCIe 模块 ABI 待核；教程中的“一键脚本”有写入副作用，不能当作只读检查。

下一步验证NPU shape/M=1/copy/内存峰值；PCIe QKV/output小包往返与30层依赖；FPGA DDR和Attention-only B golden/synthesis。沿用原50天D1，不重置日期。

stories15M/42M/70M仅reference/必要单元调试；旧全FPGA/GEMV/FPGA LM Head见 [历史架构](COMPUTE_ARCHITECTURE_FULL_FPGA_HISTORY.md)、[REVIEW](REVIEW.md)，不再作为主线阻塞。

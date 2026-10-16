# Attention + DDR 单层对拍交接（2026-10-14，更新 2026-10-16）

## 当前交接状态（2026-10-16）

- 用户已确认功能 bit 烧录完成；COM4 最新采集识别到功能版标识。
- 清空旧串口缓存后，以 115200 / 8N1 读取 8 秒，连续 16 条均为 `S:A7 F:A3002030`。
- PLL locked=1、DDR init done=1、DDR ready=1；endpoint fault=0、cal_err=0、endpoint error=0。
- 本次已完成的是**当前功能配置的 DDR 就绪检查**。本次没有执行新的 AXI 读写负载或 Attention 对拍，不代表整段 DDR 压测、冷启动稳定性或模型质量通过。
- 下一步由 PC2 在独占窗口执行：RESET + 30 TEST + 8 个 layer0 ATTENTION，返回完整结果给 B/PC1。
- 烧录方式（JTAG / Flash）尚未从本次用户回报中单独确认；下文加载流程约定使用 JTAG，不将其当作本次实际烧录方式的证据。

UART 原始记录位于 B 本地：
`E:\KVmix\fpga_attention_ddr_20261014\uart_functional_20261016_205551.txt`，
SHA256：`79FA96C016E0D81A37111EE76DD8A940EA0EF4915266AB6E7879E37F1ADCADA2`。
解析结果为同名 `.json`，状态 `passed_functional_ddr_readiness`，Attention 仍为 `NOT_RUN`。
16 条状态是同一次就绪状态的重复采样，不是 16 轮 DDR/Attention 测试。
原始采集和解析结果保持在 B 本地，本次 Git 提交仅同步交接说明及 README 入口。


## 可交付结果

FPGA 功能数据通路已接回真实 ui_ddr：H2C v2 解析 → FP16 KV append 到 DDR →
按实际历史长度读取 K/V → GQA/QK/softmax/PV → FP16 输出 → CRC 响应 → C2H。
RESET、TEST 与 ATTENTION 共用协议，不新增 opcode、BAR、门铃或生产 policy 配置。
触发是自动按 v2 帧处理；无需写 start 寄存器。

唯一交付的功能 bit：
`E:\KVmix\fpga_attention_ddr_20261014\attention_ddr.bit`。

SHA256：`C510C4FBA08D76B82FC5B1773BF460E60E920F12488627FF4BC64D09A9FAB378`。
TD 工程：`E:\KVmix\fpga_attention_ddr_20261014\attention_ddr.al`。
顶层 imx415_pcie_top，PH1A90SEG324 / speed -2。
原厂工程和已实测的 DDR-only 诊断工程未修改。
功能 RTL、TD 工程和 bit 为 B 本地制品；本次提交交接文档，不代表这些制品或 PC2 操作包已上传 GitHub。

配置为 **B / FP16 KV storage / MAX_T=64 / LAYERS=30 / SCORE_SHIFT=3**。
仅计划验证 layer0，位置 0..7；layer_stride=64*768=49152B。
超过 63 的 ATTENTION position 被拒绝；T=256、多层和 U/M 不在本版验收范围。
Q/K/V 在计算时转换为候选 Q8.8，softmax 为 LUT + Q0.16；不是全 FP16 Attention。
D=64 的 dot 分数先除以8，再进行32位饱和，匹配1/sqrt(D)的尺度。
生产数值格式和模型质量仍需 PC1/数值 Gate 审核，不能从合成向量关闭 NUM/KV UNKNOWN。

## 构建与本地验证

最终 P&R：setup WNS +0.257ns、hold WNS +0.020ns、TNS=0，STA 覆盖率 99.19%。
全工程 LUT6=22032，Slice=27073，ERAM=98/272，DSP=4/240。
物理资源表保留 attention_engine（25 ERAM/4 DSP）及 GQA/attention 实例。
仍有旧摄像头接口的无时钟/外部延迟等检查项；不称为全工程时序/CDC签核。
分布式 RAM 仍存在（4712 LUT），没有实现“完全不用 disRAM”的目标。

关键修复：

- AXI BVALID 必须与 BREADY 握手后才完成写入；外部 wr_valid 控制真实传输。
- AXI read beat 计数、ID/RESP/RLAST 和有限无进展超时检测；故障停止，无自动 KV 追加重试。
- DDR readiness 丢失使跨时钟桥与历史会话失效；未完成 AXI 事务需操作者决定完整恢复。
- GQA 输入采用 group/token/dimension 计数器，移除可变 context 除法。
- QK/PV 乘法累加分拍；输入、输出格式转换及 softmax 读/查表/累加流水线。
- 顶层 DDR 信号声明放在首次使用前，并显式 assign ready，避免 TD 将未驱动 ready 置0后裁剪计算。
- 源时钟与目的时钟间保留异步分组；移除错误的同步器第一级到第二级 false_path。

本地证据：

- 9 个原算子/完整 endpoint/历史长度回归通过（含 T=1,2,3,8,64,128,256 的独立历史测试）。
- 新功能 profile 的 125MHz/133.333MHz CDC + AXI DDR 模型通过 **19 帧/1262 响应拍**：
  RESET → TEST → T2位置0..7 → RESET → T1位置0..7；每个1152B Attention输出逐字节比较。
  这同时覆盖历史追加、GQA有符号V、非零QK缩放、position5的4KiB拆分、RESET后的新历史。
- 输入/输出转换各覆盖全部65536种16位输入，含valid间隔和最后元素tag，结果与原组合转换一致。
- RESET/TEST CDC 62例通过；主机20项既有测试、2项序列扩展测试及39请求离线预检通过。

这些是仿真、PC测试和构建证据。**当前新功能 bit 的实板 Attention 对拍尚未执行。**
实板证据包括此前 DDR-only 读写自测，以及本页新增的 2026-10-16 功能版 DDR 就绪检查；后者不替代真实 Attention 对拍。此前读写自测说明在 B 本地 `E:\KVmix\fpga\docs\DDR_BOARD_SELFTEST_20261014.md`。

## B：加载与 UART 确认

使用上面的 bit 和 hash，在协调好的独占窗口由操作者 JTAG 下载到当前 FPGA。
这会重新配置 FPGA、清空该配置的协议/Cache状态，可能影响现有 PCIe 链路和 DMA。
失败时恢复此前已验证的功能 bit；本轮不写 Flash、不自动重启/rebind/加载驱动。
仓库 COOPERATION.md 规定“实板由用户执行一组明确命令并返回完整日志”。
`load_jtag_by_operator.tcl` 是供操作者审阅/执行的脚本，助手未运行下载命令。

FPGA UART COM4，115200 / 8N1。本版格式：

```text
S:A7 F:A3002030
```

以上也是 2026-10-16 本次 COM4 采集到的实测输出：8 秒、16 条一致，cal_step=0x20。该标识与功能 profile 一致，但 UART 不回读整个 bit 的 SHA256；精确制品身份仍需结合操作者实际加载文件及其 hash。
S 高半字节 A 为功能模式标识；低4位依次是 [3]endpoint fault、[2]DDR ready、[1]init done、[0]PLL locked。
F 字节依次为 A3（本版标识）、cal_err、cal_step、{score_shift=3,error_code}。
正常是S=A7、cal_err=0、error_code=0；cal_step按实测保留，不根据step猜测完成。
旧版 S:B7 是 DDR-only 自测状态；S:0F 是旧摄像头调试状态，不能当成本功能版ready证据。
BAR0旧PHASE9版本字不用于鉴别本bit，身份用用户下载路径/hash与UART标识佐证。

## PC2：一次性实板操作包

操作包：`E:\KVmix\fpga_attention_handoff_20261014.zip`。
包大小：95366B；SHA256：`2AA1E6C2D89BC0D2DF90D39FC7B0511AA6BF654FB8057AA9D74A115B3DCAE17A`。

**操作包需由 B 另行交给 PC2。仅拉取本页 Markdown 不会获得完整 runner 和 reference；不要直接运行旧分支的同名代码替代。**
收到包后先核对 SHA256，再解压到 PC2 自己的新目录。下列命令在解压后的操作包根目录执行。
本次未上传 ZIP、bit 或个人测试结果，也未在 RK 上执行实板请求。

其中包含本地主机runner、固定/浮点reference、契约与真实SGDMA adapter、binding和已验证向量。
transport/contract依赖来自GitHub main归档commit `b286d63c3a18c02c0d918ccb6872c47406080696`，没有改PC2代码。
无需pip安装，Linux Python>=3.10，必须主线程；Windows只支持--check/离线测试。

由PC2解压到自己的新目录，并确认没有旧常驻C2H reader或另一操作者并发访问设备。
确认原BDF/设备节点/驱动仍正常，异常时先交由PC2核对链路，不自动执行任何恢复脚本。
进入操作包根目录：

```sh
mkdir results
python3 -B board_attention/runner.py --vendor-root . --binding pcie_transport/bindings/board_20261011.json --check --test-rounds 30 --tokens 8 --max-t 64 --score-shift 3 --start-seq 1
python3 -B board_attention/runner.py --vendor-root . --binding pcie_transport/bindings/board_20261011.json --test-rounds 30 --tokens 8 --max-t 64 --score-shift 3 --start-seq 1 --timeout 5 --out results/run01 --operator-note "B bit=C510C4FBA08D76B82FC5B1773BF460E60E920F12488627FF4BC64D09A9FAB378; 填入操作者和板卡信息"
```

--check不打开设备。实跑是单个会话：RESET seq1 → 30 TEST seq2..31 → 8 ATTENTION seq32..39。
不要先启动官方30轮脚本，再从seq1启动此runner。RESET不重置FPGA的last_seq。
若本bit已有请求，先核对最后seq并约定更大的--start-seq；不能猜测或自动重试。
position5检查current KV写跨4KiB边界；逐位置history从1增长至8。
每个Attention响应576个FP16字（1152B），使用同一FPGA算术参考做精确比较，另记录浮点softmax误差。

## 回传与成功条件

- summary.json：status=passed_single_layer_comparison、completed_requests=39、attention_outputs=8。
- 8个Attention报告各word_count=576、bit_exact=true、finite=true，无CRC/seq/op/layer/position失败。
- 提供summary、manifest、原始H2C/C2H二进制和每帧JSON，附bit hash、操作者、kernel/driver/runtime。
- 浮点误差只作候选数值统计，不把fixed reference精确一致当成Smol模型质量通过。
- 任一错误立即停止并保留全输出，不追加/重试KV，不从CPU返回结果替代FPGA。
- 超时/错误后RESET未必能排空已接受的AXI事务；需要操作者核对DMA/DDR/配置恢复。
- runner RTT包括证据落盘，不能直接与裸PCIe延迟或FPGA计算时间比较。

PC2返回证据后由B/PC1复核实板结果；通过后再扩大上下文、多层以及U/M。

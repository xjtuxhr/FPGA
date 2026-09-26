# 按需查阅的原始资料

日常从根目录 PLAN.md 开始。原论文和用户提供的选题指南保持根目录原路径，没有修改。

| 开发到哪一步 | 查什么 |
|---|---|
| 确认 PH1A 资源、型号 | [DS900](hardware/DS900_PH1A_Datasheet.pdf) |
| 片内 RAM 模式、宽度和端口 | [UG902 ERAM](hardware/UG902_PH1A_ERAM.pdf) |
| DSP 乘法/累加的映射 | [UG904 DSP](hardware/UG904_PH1A_DSP.pdf) |
| 需要显式器件原语时 | [UG910 HDL 库](hardware/UG910_PH1A_HDL_Libraries.pdf) |
| 当前KV DDR bring-up | [旧 UG915](hardware/UG915_PH1A_DDR_old.pdf)，必须核对当前工具与SEG324板级例程 |
| 当前每层tensor PCIe交互 | [UG913 PCIe](hardware/UG913_PH1A_PCIE.pdf)，器件支持不证明板级lane或有效延迟 |

这些手册不能代替实际板卡原理图/约束/工具说明。当前已冻结方案C与Smol135M，不再把DDR/PCIe列为将来扩展；模型参数见 [模型事实](../docs/MODEL_AND_PC_RESULTS.md)，活动问题见 [Registry](../docs/UNKNOWNS.md)。

## 当前RK CPU/NPU与PCIe证据入口

- 本地RKLLM转换示例：learningresources/03_course/05-AFC03教程RKLL人工智能篇/转换脚本/export_rkllm_qwen2.py。仅Qwen示例，不证明Smol分层NPU可用。
- 本地异构PCIe工程：learningresources/03_course/07_异构方案/AFC03_IMX415_PCIE_X1，内含deploy/sgdma_drv、diag_dma_test.sh及RKNN Lite wheel；视频DMA例程不等于QKV小包协议或latency结果。上述路径均位于根目录MLK-AFH03-AFC03下。
- 本地Linux镜像：learningresources/03_course/07_异构方案/mlk-AFC03-debian-v1.2.1.img；本轮不烧写或配置。
- [官方RKNN MatMul API示例](https://github.com/airockchip/rknn-toolkit2/tree/master/rknpu2/examples/rknn_matmul_api_demo)、[接口头](https://github.com/airockchip/rknn-toolkit2/blob/master/rknpu2/runtime/Linux/librknn_api/include/rknn_matmul_api.h)：用于确认实际shape/格式与M=1 benchmark，须匹配RK3576 SDK/runtime版本，不用支持列表冒充实测。
- [官方RKNN runtime接口](https://github.com/airockchip/rknn-toolkit2/blob/master/rknpu2/runtime/Linux/librknn_api/include/rknn_api.h)与[RKLLM](https://github.com/airockchip/rknn-llm)：分层外部Attention调度/共享内存能力需验证，不能假设现成零拷贝或现成callback。

evidence/ 内是已有官网抓取快照：DDR IP 名录只证明曾找到相关条目，产品页文本用于追溯资源数。它们不是已经验证可工作的 IP。其余旧抓取材料统一进入 archive/2026-09-21/，需要追溯时按清单找回。

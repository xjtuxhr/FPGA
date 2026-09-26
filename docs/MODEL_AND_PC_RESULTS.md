# 模型参数与 PC 评测证据

核查日期：2026-09-26。这是模型事实与PC报告的入口，不是FPGA完成证明；开放问题统一在 [UNKNOWNS](UNKNOWNS.md)。

## 1. SmolLM-135M：FACT

这里指 **HuggingFaceTB/SmolLM-135M**，不是SmolLM2-135M，也不是第三方70M。证据为本地 `models/SmolLM-135M/config.json`、实际 `model.safetensors` 的JSON header，以及 [官方config](https://huggingface.co/HuggingFaceTB/SmolLM-135M/blob/main/config.json)。本轮没有运行/重新量化模型，只读配置和张量头。

| 属性 | 核验结果 |
|---|---|
| 架构 | LlamaForCausalLM，decoder-only，GQA，SwiGLU |
| Transformer block / hidden / FFN | 30 / 576 / 1536 |
| Q heads / KV heads / head_dim | 9 / 3 / 64；每个KV头服务3个Q头 |
| vocabulary / native context | 49,152 / 2,048；首版板上预算仍64/128/256 |
| Q / K / V / O矩阵 `[out,in]` | `[576,576]` / `[192,576]` / `[192,576]` / `[576,576]` |
| gate / up / down | `[1536,576]` / `[1536,576]` / `[576,1536]` |
| embedding / LM Head | `[49152,576]`；config明确tie_word_embeddings=true；本地仅保存embedding，无独立lm_head张量 |
| 投影bias | attention_bias=false、mlp_bias=false |
| norm / activation | RMSNorm，epsilon=1e-5；SiLU/SwiGLU |
| RoPE | theta=10000，rope_scaling=null；[HF v4.41.2 rotate_half](https://github.com/huggingface/transformers/blob/v4.41.2/src/transformers/models/llama/modeling_llama.py)配对前后半维，[llama2.c](https://github.com/karpathy/llama2.c/blob/master/run.c)配对相邻维；直接复用必须先重排/对拍 |
| BOS / EOS | config均为0；prompt/chat模板、是否自动添加和停止规则仍需tokenizer实测 |
| config声明dtype | bfloat16 |
| 本地权重实际dtype | **F32**，272个张量，文件538,090,408 B；不因config声明BF16就把本地文件当成半精度 |
| 实际保存参数 | **134,515,008**；从header各shape的元素数求和，未加载大型依赖 |
| tokenizer | 词表/vocab、merges、tokenizer.json/config/special_tokens均在本地；部署格式与encode/decode仍需验证 |

本地哈希（仅固定这些文件，不证明PC报告使用同一checkpoint）：

| 对象 | SHA-256 |
|---|---|
| config.json | `a1fe6f43e20f7a6c6dbc6380222af9526b5cef262446391a281c038249e3e3b7` |
| model.safetensors | `c7a387d6fe81ca6dd304aeb809bda3932ff1bbef3ca41c9484502f2f448dc093` |
| tokenizer.json | `9ca9acddb6525a194ec8ac7a87f24fbba7232a9a15ffa1af0c1224fcd888e47c` |

参数公式（DERIVED）：`D*V + L*(2*D*QH*HD + 2*D*KVH*HD + 3*D*FFN + 2*D) + D`。输出head与embedding共享，norm单独计入。脚本自检同时验证134,515,008。

本地Karpathy header也已核对：15M=`(288,768,6,6,6,32000,256)`；42M=`(512,1376,8,8,8,32000,1024)`，字段为D/FFN/L/QH/KVH/正vocab/context。正vocab表示shared classifier；42M参数公式为41,689,600（.bin另含RoPE数组，文件字节数不等于参数数×4）。

## 2. PC报告：报告提供的结果，不冒充独立重跑

来源：根目录 [summary_of_PCtest.pdf](../summary_of_PCtest.pdf)，共3页，本轮完整读文本并核对第1页表格。使用纯PyTorch量化/反量化数值实现；内存压缩按理论bit packing含scale/min估计，**没有FPGA资源/频率/吞吐或实际CUDA显存证据**。

| 模型 | 数据集 | FP16 PPL | U PPL | M PPL | U−M |
|---|---|---:|---:|---:|---:|
| stories15M | TinyStories | 3.87 | 4.21 | 4.21 | 约0 |
| stories42M | TinyStories | 3.49 | 3.69 | 3.72 | −0.03 |
| Qwen2.5-0.5B | Wikitext-2 | 14.69 | 18.34 | 18.12 | 0.22 |
| SmolLM-135M | Wikitext-2 | 19.76 | 23.90 | 22.64 | 1.26 |

U/M PPL由报告基线加绝对增量恢复，受原表四舍五入影响。报告Smol优势约6.3个百分点、Qwen约1.6个百分点；不要用四舍五入表反推精确原始统计。Smol的M相对B仍退化约14.6%，不是无损恢复。报告图中15M约−0.1 pp与表中约0是舍入差异，不能强行解释。

## 3. 影响工程的设置与冲突

- 报告按 `max(1,int(0.1*N))` 选择重要层，小于10层避免零层。预算现默认同样计**数量**；真实K/V层ID各自离线选择，脚本不做profiler，也不宣称两套重要层相同。
- 15M的head_dim48：报告因上游整除约束用group16；42M可用group32。脚本支持末尾部分组，默认32是FPGA候选布局，不是15M PC精度复现。
- 报告的K3是11元素/int32、10个3-bit+1个2-bit；脚本默认dense完整3-bit，`--k3-packing cuda11`可估容量差异，但不能复现质量。
- 报告采用prefill+分块decode评分，声明与逐token logits一致；尚缺脚本/日志，不能独立验证。FPGA PPL仍须逐位置通过真实Cache计算；prefill全精度的上游行为与本项目全程U量化不同，需对齐。
- 报告未提供上下文、样本量/方差、RPC精确比例/长度、U是否同样带tail、group具体值、scale dtype、代码commit、checkpoint hash；**不自动把报告U等同PLAN的无tail U**。
- 跨模型/数据集/tokenizer的PPL不能直接排名。报告“收益随模型规模增长”的说法不能由四点证明，135M与0.5B参数量顺序相反；最多描述这几组实验中的关联，因果需控制变量。
- 5%–9% PPL退化不等于“没有精度损失”；小stories的证据是M没有比U更好，不是U本身完全无损。也不能仅凭这些结果证明梯度选层有效，需tail-only和相同字节预算随机选层消融。

## 4. 当前冻结决定：方案C + Smol135M

团队正式选择HuggingFaceTB/SmolLM-135M作为第一次完整上板模型，采用RK3576 CPU/NPU + FPGA Attention的方案C。stories15M/42M/70M只作reference/必要单元调试；40–80M替代模型搜索不再是主线门槛。本地F32权重、PC FP16基线和未来NPU量化制品相互独立，需要重测异构数值路径。上列本地hash已知，但正式制品签核及PC评测是否同一版本仍UNKNOWN。

下一步在目标长度64/128/256对齐PC设置，验证NPU真实shape/M=1与PCIe小包，然后Attention-only FPGA bring-up。模型与方案不再待选，实际可运行性/质量仍需证据；不裁剪原模型或把配置支持冒充实测。

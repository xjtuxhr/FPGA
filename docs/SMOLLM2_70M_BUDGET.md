# REFERENCE ONLY：codelion/SmolLM2-70M下载与历史全FPGA预算

团队随后正式冻结方案C + Smol135M，70M只作参考/必要单元验证；以下下载事实保留，旧容量结论不指导当前架构。预算命令须添加 `--architecture full_fpga`；当前说明见 [BUDGET_GUIDE](BUDGET_GUIDE.md)。下文“没有改为NPU路线”仅描述当时任务边界，不是当前项目状态。

日期：2026-09-26。模型已下载；只做文件/header校验和预算，没有运行模型、KVmix质量评测、RTL综合或板上推理。没有把它冻结为正式主模型，也没有改为RK3576 NPU计算路线。

## 1. 下载与模型事实

- 来源：[codelion/SmolLM2-70M](https://huggingface.co/codelion/SmolLM2-70M)。
- 固定revision：`285b36e5a47639324f5ec41679020c7d8fd19a5c`。
- 本地目录：`models/SmolLM2-70M/`。
- 已下载该revision全部10个仓库文件：`.gitattributes`、`README.md`、`config.json`、`generation_config.json`、`merges.txt`、`model.safetensors`、`special_tokens_map.json`、`tokenizer.json`、`tokenizer_config.json`、`vocab.json`。
- 9个普通文件长度及Git blob SHA-1与Hugging Face文件清单一致；权重长度和LFS SHA-256一致。未执行模型卡中的代码或安装依赖。

| 属性 | 实际config/header证据 |
|---|---|
| 架构 | LlamaForCausalLM，SwiGLU/SiLU，RMSNorm，无QKV/MLP bias |
| layers / hidden / FFN | 32 / 384 / 1024 |
| Q/KV heads / head_dim | 6 / 2 / 64，GQA每KV头对应3个Q头 |
| vocab / 原生context | 49152 / 8192；项目首版仍只预算64/128/256 |
| RoPE | theta=100000，无scaling；不同于SmolLM-135M的10000，不能复用其ROM值 |
| BOS/EOS | config均为0；运行时语义仍需tokenizer/reference验证 |
| embedding/head | config tie=true；header只有embedding、无独立lm_head |
| 参数量 | **69,230,976**，header逐tensor形状求和与预算公式一致 |
| 实际文件dtype | **BF16**，290个tensor，不是已导出的W8模型 |
| 权重文件长度 | **138,494,280 B**（含safetensors header） |

哈希：

```text
model.safetensors SHA256:
e777a572b1103d8b91543c1e2bdb632d1aeec9bb3879fac90a27b4ce45c92a17
config.json SHA256:
b86ac8fcd974da5c3b42656c0492bc4aa5b575b4a9a81fa5373cbf256cca6940
tokenizer.json SHA256:
7d27c493c729a66ecefc837280b05d948b1ed50d130eebdbf911b1b36cf38ed7
```

## 2. 采用的原路线及显式假设

完整embedding、32个block、LM Head及KVmix均在PH1A90SEG324；RK3576只分词/控制/选token，不计算linear或Attention。W8权重与全部KV常驻FPGA的256 MiB DDR；当前层buffer放680 KiB ERAM，不计disRAM或RK侧LPDDR为FPGA本地存储。

预算入口 `tools/budget_check.py --model smol2_70m`。为可比性，保留与Smol135M相同的候选默认值，而不是因为模型更小就无证据压缩buffer：激活/控制256 KiB、tile128 KiB、KV buffer64 KiB、完整32-bit logits192 KiB；另留64 KiB ERAM；权重附加空间4 MiB。

M预算重要K/V各3/32层、tail32、group32、dense K3、metadata4 B/组；U全层全token K2/V2且无tail。这些不是PC质量证据或冻结RTL。缓存总量已经包括metadata和M的FP16 tail。DDR表不含另行分配的额外scratch/双份权重；保留的约182 MiB以上余量不是允许随意忽略它们。

## 3. DDR结论：足够

W8裸权重为 `69,230,976 B = 66.023804 MiB`。

| 总长度T | B KV MiB | U KV MiB | M KV MiB | W8+4 MiB附加+B KV | 同口径U | 同口径M |
|---|---:|---:|---:|---:|---:|---:|
| 64 | 1.000000 | 0.187500 | 0.598145 | 71.023804 | 70.211304 | 70.621948 |
| 128 | 2.000000 | 0.375000 | 0.794434 | 72.023804 | 70.398804 | 70.818237 |
| 256 | 4.000000 | 0.750000 | 1.187012 | 74.023804 | 70.773804 | 71.210815 |

T256的U/M metadata分别为0.250000/0.218750 MiB，已包含于KV总量。全部低于256 MiB。最保守的表内W8+B场景仍剩约181.976 MiB。

完整16-bit裸权重为132.047607 MiB；加4 MiB附加和T256 B KV后约140.047607 MiB，也放得下。BF16与FP16容量相同，但数值不同；这不意味着原路线实现了BF16/FP16浮点计算。F32裸权重约264.095 MiB，单权重即超过256 MiB，不是首版路线。

## 4. ERAM结论：原buffer预留超限；小改tile可通过

词表没有缩小，完整32-bit logits仍需 `49152×4=196608 B=192 KiB`。

```text
原候选：256 + 128 + 64 + 192 = 640 KiB
加64 KiB候选IP/额外预留 = 704 KiB > 680 KiB，超24 KiB

仅改weight tile为64 KiB：256 + 64 + 64 + 192 = 576 KiB
加64 KiB同样预留 = 640 KiB <= 680 KiB，余40 KiB
```

因此**只换70M并沿用全部默认buffer，并不能使原预留方案通过**；但不换计算路线、不压缩logits、不用disRAM，仅减小候选weight tile就可通过容量预算。64 KiB tile的burst效率、banking、ERAM块粒度/端口和真实IP资源仍需综合验证，不能视为已经布局成功。所有权重/KV都放ERAM则仍不可行。

## 5. 算术与验收边界

```text
固定linear MAC/token = 69,206,016
Attention MAC/token = 2×32×6×64×T = 24,576T
T64/128/256总MAC = 70.778880 / 72.351744 / 75.497472 M
W8主矩阵/head+embedding一行读取 = 69,206,400 B，约66.000 MiB/token
```

脚本100 MHz/16lane/2DSP每lane/25%MAC利用率候选仍只用32个核心DSP，加32预留为64/240；T256 MAC阶段约5.298 tok/s，**不是整模型吞吐**。实际DDR带宽、非线性、量化/迁移、LUT/DFF、时序和W8质量仍未测。

这个70M模型是否保留Smol135M报告中的KVmix收益**尚未验证**。训练数据、模型版本、层数和RoPE不同，不能外推PPL结果，也不能仅凭“放得下”冻结正式模型。

## 6. 可复现命令与验证

```powershell
python tools/budget_check.py --architecture full_fpga --self-test
python tools/budget_check.py --architecture full_fpga --list-models
python tools/budget_check.py --architecture full_fpga --model smol2_70m --contexts 64 128 256
python tools/budget_check.py --architecture full_fpga --model smol2_70m --contexts 64 128 256 --weight-tile-kib 64 --verdict-only
python tools/budget_check.py --architecture full_fpga --model smol2_70m --contexts 256 --weight-bits 16 --weight-tile-kib 64 --verdict-only
```

本轮已检查全部下载文件、header290个tensor及每层矩阵shape；确认脚本preset与本地config一致。self-test加入70M参数/MAC/KV/metadata、W8/W16 DDR通过、F32 DDR失败、原ERAM预留失败和缩tile容量通过的断言。当前tools目录仍被Git忽略，未修改忽略规则、提交或推送。

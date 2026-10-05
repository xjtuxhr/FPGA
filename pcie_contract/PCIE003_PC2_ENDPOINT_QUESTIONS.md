# PC2 → B：PCIe endpoint / bitstream 依赖（打通枚举前）

> 来自：PC2。承接 `PCIE003_FPGA_REPLY2.md`（Q1–Q3 已接受，spec 已定稿 v0.2）。
> 目标：澄清"打开 RK 控制器后，FPGA 端到底有没有可枚举的 endpoint"。

## 背景

- PC2 已备好 RK 侧维护：把 `pcie@2a210000` 从 `disabled` 改 `okay` + 重启（`PCIE_BRINGUP_RUNBOOK.md`）。
- 但**只打开 RK3576 的 PCIe 控制器，不等于有端点**：需要 FPGA 侧真的**呈现一个 PCIe endpoint（SERDES/SGDMA）**，否则 `lspci` 仍为空。
- 现状：你本轮提交（`d43ae0b`）加了 `q88_to_fp16.v` + 文档，**仍未见 PCIe 物理 endpoint**。

## 问题

1. **Q1**：FPGA 侧当前是否有**带 PCIe endpoint（SERDES + SGDMA）** 的 bitstream？还是目前只有纯逻辑 `attention_b_top` / KV 数据通路？
2. **Q2（若有）**：请给出该 bitstream 的 **sha256 + 烧写方式**（JTAG 还是上电由 RK 加载），PC2 用它做**首版链路**（原始 1920B 下发 / 1152B 返回）验证。
3. **Q3（若没有）**：能否**先用厂商 PCIe 例程的 bitstream** 打通链路（已知 pattern）？这样可以先把「枚举 → 驱动 → 往返」解决，不被 attention endpoint 阻塞；之后的 endpoint 再接 attention。
4. **Q4**：endpoint 计划里，H2C/C2H 走 SGDMA 的**哪个用户设备**？`TLAST/TKEEP`、背压、完成通知是否与官方例程一致（PC2 据此绑 `TRANSPORT_BINDING`）。
5. **Q5**：status 字（`[0]DONE / [3:1]ERR`）落在 endpoint 的**哪个寄存器**、经哪个节点 4B 读？（枚举后填地址）

## 备注

- 只要给出 Q1–Q4，PC2 就能在枚举打通后独立完成：原始链路 → framed v2 `TEST` 30 轮 → 填 binding。Q5 可等 endpoint 出来再对齐。
- 线格式仍沿用契约 v2，无需改动。

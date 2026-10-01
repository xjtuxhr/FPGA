# Transport binding：先验证，再填值

状态：**UNBOUND**。本文件是验收/证据模板，不是可执行配置。UNKNOWN 的状态只在 `docs/UNKNOWNS.md` 更新。未完成绑定时 codec 只在 PC 使用，不打开设备、不写 BAR。

## 已选择的实现方向

沿用官方 SGDMA 字符设备：H2C/C2H 传 tensor；控制优先 user 节点的 32bit pread/pwrite。暂不引入新 kernel driver、raw mmap 或最终 production register map。

本地官方源码说明：user 字符设备有 `SGDMA_USER_BAR_BASE_OFFSET=0x80000`，control read/write 每次 4B；raw ioctl/mmap 与 user 节点的 offset 语义不同。**源码事实不是当前板卡绑定证据**，不得将逻辑 offset=0 自动写到实际 BAR=0。

## 每次 transport 交接必须填写

| 项目 | 需要的证据 |
|---|---|
| 制品 | 源码 commit、contract 版本、driver/module 和 bitstream SHA256 |
| 板卡 | SEG324/BOM、RK kernel、执行用户/组、NPU/PCIe runtime 环境 |
| 枚举 | BDF、vendor/device ID、绑定 driver、BAR resource 大小与权限 |
| 节点 | H2C/C2H/user/control 的真实路径、channel、访问权限；不能只按脚本名称猜 |
| 地址公式 | 所用 API、BAR index、driver base、application logical offset、最终 endpoint 地址；逐项记录 |
| 数据模式 | AXI-MM 还是 AXI-ST；AXI-MM device buffer 区域/容量，或 AXI-ST TLAST/TKEEP/背压 |
| DMA 限制 | user buffer 和 device address 对齐、length granularity、最大长度、合法 padding、coherence/sync |
| 提交/接收 | 先准备 C2H 还是先写 H2C；写返回的含义、输入可见性、请求 accepted 的确认 |
| 完成/消费 | DMA 完成与 Attention 完成分别如何确认；返回 seq、旧 DONE 清除/ACK、读回后消费 |
| 超时/错误 | finite monotonic deadline、driver timeout/cancel 限制、short read/write、错误代码及恢复隔离 |
| 计时 | clock、边界、poll 间隔/CPU 占用、min/mean/max/p95、30轮总时间 |
| 正确性 | 逐轮 counter、完整逐字节比较、corruption/error count、原始或 framed profile 标记 |

未取得的字段保留 UNKNOWN，提交带版本的 binding 证据后才能接到正式 backend。当前不用整数毫秒 `attn_ms` 当唯一性能计数器；应用用 monotonic 高分辨率时间，未来 FPGA cycle counter 另记录频率/回绕。

## 完成状态的最低要求

1. 每次只有一个在途请求，seq 不复用；旧帧/旧状态不能满足新请求。
2. 输入传输/同步完成后才通知 FPGA；仅 posted write 返回不够。
3. RESULT_READY 意味输出已稳定，但不代表已完成 C2H 到 host 的同步。
4. 按 binding 完成完整读回与校验，再消费/清状态并释放请求。
5. AXI-ST 必须验证接收准备和背压不会让 H2C/write 或 FPGA 永久阻塞。
6. 若需要 DMA padding，binding 在 transport 外层明确处理，codec 只看到精确逻辑帧。小于 header 的 reset 帧长度 32B 也必须验证传输粒度。
7. 保留官方 DMA 完成中断，不将应用 polling 与 driver IRQ 混为一谈。

## 实板步骤的边界

先只读确认当前枚举/driver/节点与工程，取得操作者空闲确认后才做单一数据测试。读取未知 BAR 寄存器也可能有 read-to-clear 副作用，不视为自动安全。

需重配置 FPGA、加载模块、rebind/rescan、修改 DTB/镜像/系统库时，先停下并列出目标、影响、备份/恢复与批准；不运行原一键脚本。任何失败保留 stdout/stderr，不继续 Attention/30层集成。

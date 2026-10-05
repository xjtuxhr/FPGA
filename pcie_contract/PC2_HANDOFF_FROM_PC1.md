# 给PC2：PCIe1 boot修补方案需重做解析入口

状态：只读审核结论，**不是写盘/重启授权**。PC1不覆盖PC2目录，v33等待本窗口处理并释放；不同时做NPU/PCIe实验。

## 已确认，勿重复猜测

- live `/pcie@2a210000/status=disabled`，但不证明只改status就能训练/枚举。
- p3开头为FIT外层FDT，1536B SHA256 `7da2d9cf5fb76c51657a46be8c02629429319b2c2ccddcb946076a1b4c9acc3b`。default=conf；该配置引用fdt/kernel/resource。
- `/images/fdt`声明position=0x800、size=0x46fdc(290780B)、compression=none，记录的SHA256为`a30ce31326022e507ba8a4c751a11afc70770a471a6f2d8009641b69815fa3dd`。payload尚未取回/hash核验，不把offset字段直接当写盘许可。
- 收到的旧patch SHA256 `dffb837b14955906ee4f12ae658c075ed3dd1da0a831eed809278c8cc09ae0a9`。其find_status_prop对actual接收的1536B，在PC内存复现找不到节点；main会先找节点再备份/写盘，不能启用PCIe。不要通过skip-running-check、硬编码偏移或扫magic绕过。
- signature节点仅见配置元信息，无value；是否实际验签未确认，不提前断言必须重新签名或可忽略签名。
- `/home/kvdev/work_pc2_pcie/PCIE_BRINGUP_RUNBOOK.md`不存在。如果runbook在其他位置，请提供真实路径并修正wrapper引用/检查。

原始字段、完整JSON、可复现PC解析与边界见[证据入口](README.md)和[analysis.json](analysis.json)。

## 下一版最低提交内容

1. **实际boot离线审查/修改方案**：结构解析FIT的配置→fdt引用及external data范围，核对payload hash、硬件compatible/精确PCIe路径、PHY/reset/供电和running tree关系；说明实际启动选择及resource是否含DTB副本。根据该板启动规则使用官方兼容的hash/签名处理，不能关闭验签或盲替换整个官方镜像。先在PC普通镜像文件上验证，输出前后hash/精确diff，证明kernel/resource等不相关内容不变。若容器重打包导致布局变动，应解释并核验，而不是宣称“只改9字节”。
2. **安全写盘入口**：严格参数/设备/分区身份检查；check-only保证零写入，未知参数失败；区分普通文件测试与实板apply，不自动skip身份检查。保存完整原p3到唯一持久文件，确认字节数/full SHA、持久化和读回，并把备份取回PC；写后fsync/完整相关范围readback及未修改区域验证，失败即停止、不自动重启/重试。不用ls|tail选备份、不覆盖旧备份。
3. **真实runbook和修订文件/hash**：提供无法进Linux时也可用的恢复入口、对应制品/目标；明确一次变更副作用、实际helper清单和PC验证命令/日志。两端操作者批准同一方案、确认板卡空闲后才执行；先观察启动/目标endpoint枚举，不捆绑SGDMA、BAR、FPGA重配置、永久网络或串口共享。参数为--reboot时也必须在已验证写后条件下才允许重启。

probe后续修正：任何PCI function不等于安路endpoint；记录具体BDF/VID/PID/driver，DT大端cells解u32，板上date不要命名为PC时间。现有read-only probe不构成DMA/Attention Gate。

## 不变边界

保留SGDMA完成中断、系统RKNN runtime/driver/kernel及PC1文件/结果；本次不批准换库/镜像升级。重启可能丢失临时网络，runbook应覆盖end0=192.168.137.101/24（PC2）、end1=192.168.138.101/24（PC1）恢复与两边SSH确认，不能仅恢复PC2。

PC1当前不再要求成员重复已完成的prefix取证；下一次接收应是PC2修订源码/runbook及PC离线证据，再确定一组系统变更方案。此文件未自动发给PC2，也未推送Git，成员自行共享。

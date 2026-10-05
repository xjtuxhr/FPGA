# PCIe1 bring-up 运行手册（PC2，需协调窗口）

状态：**已备好，未执行**。本手册描述把 `pcie@2a210000` 从 `disabled` 打开所需的一次性维护操作。
它**会改 DTB 并重启整块板**，属于系统级变更：执行前必须按 [COOPERATION.md](../pcie_contract/COOPERATION.md)
取得板卡操作者与另一方的批准，并列出目标/副作用/恢复。当前不宣称任何 PCIe Gate 通过。

> **首选路线**：先用厂商 `AFC03_IMX415_PCIE_X1` 例程的 endpoint bit + 驱动打通链路（含 **PERST#/电源 GPIO**，见 [厂商参考](VENDOR_PCIE_REFERENCE.md)）。仅改 DTB status **可能不够**。FPGA 必须先烧好 endpoint bit。

## 0. 根因（只读证据，2026-10-05）

板子（`linaro-alip`，Debian 12，kernel 6.1.99）上只读观察：

- `/proc/device-tree/pcie@2a200000/status = disabled`
- `/proc/device-tree/pcie@2a210000/status = disabled`
- `lspci` 空、`/sys/bus/pci/devices` 空
- 无 `/dev/ANLOGIC*`、无 `/dev/sgdma*`
- dmesg 无 `rk-pcie` probe（平台驱动存在但未 probe）

→ PCIe 端点不出现是因为**设备树关了控制器**，不是驱动缺失。打开需改 DTB + 重启。

**重要（2026-10-05 复核修正）**：`/dev/mmcblk0p3` 是 **U-Boot FIT 容器**（外层 FDT），**不是**裸内核 DTB。真正的 DTB 是 `/images/fdt`（`type=flat_dt`、`compression=none`）在 `data-position`/`data-size` 处的 payload。
- 因此旧的 `patch_pcie1_dtb.py`（把 p3 当裸 DTB）**找不到 `pcie@2a210000`**，无法启用 PCIe（会 fail-closed）。
- 正确做法：用 `fit_dtb_patch.py` 解析 FIT → 提取 `/images/fdt` → 改其中的 `status` → 同长回写；若该 image 有 `hash` 节点需同步更新，遇到 `signature` 节点**拒绝**。
- 厂商 `07_异构教程\boot.img`（FIT）的嵌入 DTB **已经是 `pcie@2a210000 = okay`**；厂商 readme 也建议升级 `boot.img`。见 [厂商参考](VENDOR_PCIE_REFERENCE.md)。

## 1. 硬前提

1. **协调**：另一操作者明确回复“板卡空闲”，并同意重启窗口（重启会断掉所有 SSH、清掉 NPU 状态）。
2. **root 通道**：`kvdev` 无 sudo、root 密码锁定，只能用**串口 root shell**（`ttyFIQ0`）执行写盘。
3. **重启后网络**：`end0` 的 `192.168.137.101/24` 是临时的（UNKNOWN LNX-002），重启后要用串口补设。
4. **回滚准备**：补丁工具会先备份到 `/userdata`；记下备份文件名。

## 2. 窗口内步骤

### 2a. 采集改前证据（普通 kvdev SSH，只读）
```bash
bash /home/kvdev/work_pc2_pcie/probe_enumeration.sh /home/kvdev/work_pc2_pcie/evidence
# 期望：RESULT: NO_PCI_ENDPOINT，pcie@2a210000/status = disabled
```

### 2b. 串口 root shell：先只读分析 FIT（当前版本不写入）
```bash
python3 /home/kvdev/work_pc2_pcie/fit_dtb_patch.py --fit /dev/mmcblk0p3 --check
# 期望：/images/fdt 的 position/size、pcie@2a200000/2a210000 状态、是否有 hash/signature 节点
```
**in-place apply 尚未启用**（下一版：备份 → 写 → readback → 校验 kernel/resource 未变；见 §2c-待办）。
首选替代：按厂商流程**刷 `boot.img`**（其嵌入 DTB 已使能 pcie1），见 [厂商参考](VENDOR_PCIE_REFERENCE.md)。

### 2c-待办（下一版最低要求，来自 PC1 handoff）
1. FIT 离线审查/修改：核对 fdt payload hash、compatible、PHY/reset/供电、running tree；
   先在 PC 镜像文件上验证并输出前后 hash + 精确 diff。
2. 安全写盘入口：严格身份检查、check-only 零写、唯一持久备份 + 完整 SHA + 读回、fsync/readback、
   未修改区域校验、失败即停、不自动重启/重试、不 `ls|tail` 选备份。
3. 真实 runbook + 修订文件/hash + 无法进 Linux 的恢复入口；两端操作者批准同一方案、板卡空闲才执行。

### 2c. 重启
```bash
reboot
```

### 2d. 重启后：串口补网络 + 复测
```bash
ip link set end0 up
ip addr add 192.168.137.101/24 dev end0
ss -ltnp | grep ':22' || systemctl start ssh
```
回 PC 侧验证 `ping 192.168.137.101` / `ssh kvdev@192.168.137.101 hostname`。

### 2e. 采集改后证据（只读）
```bash
bash /home/kvdev/work_pc2_pcie/probe_enumeration.sh /home/kvdev/work_pc2_pcie/evidence
# 期望：RESULT: PCI_ENUMERATED，出现 BDF，可能还有 /dev/ANLOGIC*/ /dev/sgdma*
```

## 3. 若打开了控制器仍无端点

按优先级排查（详见 [厂商参考](VENDOR_PCIE_REFERENCE.md)）：

1. **FPGA 未烧 endpoint bit**：当前 FPGA 只有纯逻辑（B 已确认无 endpoint bitstream）。需先烧厂商 `imx415_pcie_4k.bit`（sha256 `CB7819...CDF`）或用 TD 生成带 endpoint 的 bit。
2. **PERST# / 电源未处理**：厂商 `pcie1_enable.sh` 会拉 **PERST#(gpio-48)**、使能 **vcc3v3_pcie(gpio-124)**，并由 systemd 服务 `pcie1-fpga` 开机执行。只改 DTB status 可能不足以释放 FPGA 复位。
3. **SGDMA 驱动未加载**：厂商 `deploy/sgdma_drv` 需编译/加载后才有 `/dev/ANLOGIC*`、`/dev/sgdma*`。

以上任一都需 FPGA 老师 / 现场配合，属系统变更，不在"仅改 DTB"范围。

## 4. 回滚（串口 root）

```bash
ls -l /userdata/p3_dtb_backup_*.bin
dd if=/userdata/p3_dtb_backup_<ts>.bin of=/dev/mmcblk0p3 bs=1M
sync
reboot
```
若板子起不来，用串口 + 供应商 USB loader / 镜像恢复。

## 5. 边界

- 本手册**只**动 `pcie@2a210000`；不 rebind、不 rescan、不改驱动、不改 rootfs。
- 不运行厂商“一键脚本”。所有失败保留 stdout/stderr，不继续下一步。
- 端点出现后，仍需完成 OP_TEST 30 轮真实数据测试，才可把证据填入
  [TRANSPORT_BINDING](../pcie_contract/TRANSPORT_BINDING.md)；在此之前 binding 保持 UNBOUND。

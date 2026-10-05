# PCIe1 bring-up 运行手册（PC2，需协调窗口）

状态：**已备好，未执行**。本手册描述把 `pcie@2a210000` 从 `disabled` 打开所需的一次性维护操作。
它**会改 DTB 并重启整块板**，属于系统级变更：执行前必须按 [COOPERATION.md](../pcie_contract/COOPERATION.md)
取得板卡操作者与另一方的批准，并列出目标/副作用/恢复。当前不宣称任何 PCIe Gate 通过。

## 0. 根因（只读证据，2026-10-05）

板子（`linaro-alip`，Debian 12，kernel 6.1.99）上只读观察：

- `/proc/device-tree/pcie@2a200000/status = disabled`
- `/proc/device-tree/pcie@2a210000/status = disabled`
- `lspci` 空、`/sys/bus/pci/devices` 空
- 无 `/dev/ANLOGIC*`、无 `/dev/sgdma*`
- dmesg 无 `rk-pcie` probe（平台驱动存在但未 probe）

→ PCIe 端点不出现是因为**设备树关了控制器**，不是驱动缺失。打开需改 DTB + 重启。

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

### 2b. 串口 root shell：先 dry-run，再打补丁
```bash
python3 /home/kvdev/work_pc2_pcie/patch_pcie1_dtb.py --check-only
# 期望：status = b'disabled\0'，且 [cross-check] p3 DTB matches running kernel DTB

python3 /home/kvdev/work_pc2_pcie/patch_pcie1_dtb.py
# 行为：写 /userdata/p3_dtb_backup_<ts>.bin → 原地把 pcie@2a210000 改为 okay → 复查
sync
```
工具失败即停（`PATCH_FAILED`），保留输出，不要手工改 DTB。

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

大概率 **FPGA bitstream 未带 PCIe endpoint**（当前 FPGA 只跑通了 MIPI 通路）。这属于 FPGA 侧配置，需与 FPGA 负责人协调，不在本手册范围。

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

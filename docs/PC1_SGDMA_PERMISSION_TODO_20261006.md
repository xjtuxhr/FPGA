# 给 PC1：串口 root 待办（SGDMA 设备权限）

日期：2026-10-06　　来自：PC2
背景：RK3576 侧 PCIe1 已打通并持久化（开机自动 link up + 加载 `anlogic_pci` 驱动，节点 `/dev/ANLOGIC-PCI0_*`）。
现在需要**把 SGDMA 设备节点权限放开给 `kvdev`**，这样 PC2 后续做 DMA/往返测试不必占用 root 串口。

准备：用 **MobaXterm/PuTTY 串口 root**（`ttyFIQ0`，1500000 8N1）登录。板子已自动启动完成。

---

## 第 0 步（只读，先确认现状）

```sh
uptime
lspci -nn | grep 1edb
lsmod | grep anlogic_pci
ls -l /dev/ANLOGIC-PCI0_*
```

预期：
- `lspci` 有 `21:00.0 ... [1edb:abcd]`
- `lsmod` 有 `anlogic_pci`
- 四个节点：`ANLOGIC-PCI0_user`、`_control`、`_h2c_0`、`_c2h_0`

如果这些都正常，继续第 1 步；如果缺，先别做别的，把输出发给 PC2。

---

## 第 1 步：安装 udev 规则（放开权限给 kvdev）

```sh
cat > /etc/udev/rules.d/99-anlogic-pci.rules <<'EOF'
KERNEL=="ANLOGIC-PCI*", MODE="0660", GROUP="kvdev"
EOF
udevadm control --reload-rules
udevadm trigger
```

## 第 2 步：立即生效的兜底（若 udev 没刷新权限）

```sh
chgrp kvdev /dev/ANLOGIC-PCI0_* 2>/dev/null
chmod 0660 /dev/ANLOGIC-PCI0_*
```

## 第 3 步：确认生效

```sh
ls -l /dev/ANLOGIC-PCI0_*
```

预期变成：`crw-rw---- 1 root kvdev ... /dev/ANLOGIC-PCI0_*`

---

## 回传给 PC2 的内容

1. 第 0 步四条命令的完整输出；
2. 第 3 步 `ls -l /dev/ANLOGIC-PCI0_*` 的输出。

---

## 注意（不要做）

- **不要**运行 `pcie_setup.sh` / `pcie1_enable.sh` / `pcie1_rebind.sh` / `build_drivers.sh` / `diag_dma_test.sh`（有写盘/重编译/重绑副作用，本板已用另一套方案处理）。
- 不需要重启、不需要改 DTB、不需要写任何分区。
- 上面的操作**只改 udev 权限**，不改变板卡功能；PCIe1 和 SGDMA 已经是开机自动的。

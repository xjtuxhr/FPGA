# RK3576 开发启动 Checklist

- [ ] 板卡上电，网线连接 PC 的 **“以太网”（Realtek，不是“以太网 2”）** 与板上已验证的网口。
- [ ] PC 运行 `ipconfig`：确认“以太网”为 `192.168.137.1/24`。
- [ ] MobaXterm SSH：`192.168.137.101:22`，用户 `kvdev`；登录后运行 `hostname`，应为 `linaro-alip`。
- [ ] 若 SSH 不通，打开串口查 `ip -br addr show end0`；**仅当没有 `.101/24` 时**运行 `ip link set end0 up`、`ip addr add 192.168.137.101/24 dev end0`，然后重试 SSH。
- [ ] 仍不通，串口查 `ss -ltnp | grep ':22'`；未监听时运行 `systemctl start ssh`。

板上 IP 目前是临时设置：只重启 PC 通常可直接 SSH；板卡重启后可能需要用串口补设 IP。密码只在 MobaXterm 输入，不发送给他人。（2026-10-14 起：NetworkManager 已持久化，重启后仍为 `end0=.101`/`end1=.101`。）

## 权限与 root

- **`kvdev` 不在 sudoers**，`sudo` 直接被拒；需要 root 的操作（rebind、改 gpio、rmmod 等）用 **`linaro`**（在 `sudo` 组）登录后 `sudo`。
- PC2 直连 `end0=192.168.137.101/24`；PC1 直连 `end1=192.168.138.101/24`；两条 SSH 进同一台板，共享设备，板上实验串行。

## PCIe 端点（FPGA）

- 链路/枚举：`lspci -nn | grep 1edb`；节点 `/dev/ANLOGIC-PCI0_{user,control,h2c_0,c2h_0}`。
- **JTAG/重配 FPGA 后链路会「假 up」**：`lspci` 仍显示 `1edb:abcd`，但端点是旧的、写会 `errno 512`。必须做**完整恢复**：

  ```sh
  systemctl stop anlogic-sgdma; rmmod anlogic_pci
  echo 2a210000.pcie > /sys/bus/platform/drivers/rk-pcie/unbind; sleep 2
  /usr/local/sbin/pcie1-fpga.sh
  systemctl start anlogic-sgdma
  ```

- 冷启动已加固：`pcie1-fpga.sh`（长重试 + 失败非零退出）+ service `Restart=on-failure`；软重启实测 ~18.8s 自动 up。
- `kvdev` 可用 `op_test` 证据脚本；需 root 时走 `linaro`+`sudo`。

# RK3576 开发启动 Checklist

- [ ] 板卡上电，网线连接 PC 的 **“以太网”（Realtek，不是“以太网 2”）** 与板上已验证的网口。
- [ ] PC 运行 `ipconfig`：确认“以太网”为 `192.168.137.1/24`。
- [ ] MobaXterm SSH：`192.168.137.101:22`，用户 `kvdev`；登录后运行 `hostname`，应为 `linaro-alip`。
- [ ] 若 SSH 不通，打开串口查 `ip -br addr show end0`；**仅当没有 `.101/24` 时**运行 `ip link set end0 up`、`ip addr add 192.168.137.101/24 dev end0`，然后重试 SSH。
- [ ] 仍不通，串口查 `ss -ltnp | grep ':22'`；未监听时运行 `systemctl start ssh`。

板上 IP 目前是临时设置：只重启 PC 通常可直接 SSH；板卡重启后可能需要用串口补设 IP。密码只在 MobaXterm 输入，不发送给他人。

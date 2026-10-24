#!/bin/sh
set -x
systemctl stop anlogic-sgdma
rmmod anlogic_pci
echo 2a210000.pcie > /sys/bus/platform/drivers/rk-pcie/unbind
sleep 2
/usr/local/sbin/pcie1-fpga.sh
systemctl start anlogic-sgdma
sleep 1
echo "=== lspci ==="
lspci -nn
echo "=== lsmod ==="
lsmod | grep anlogic
echo "=== nodes ==="
ls -l /dev/ANLOGIC*
echo "=== link ==="
cat /sys/bus/pci/devices/0000:21:00.0/current_link_speed /sys/bus/pci/devices/0000:21:00.0/current_link_width

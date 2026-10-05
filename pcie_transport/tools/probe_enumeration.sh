#!/usr/bin/env bash
#
# PCIe enumeration probe (PC2, READ-ONLY).
#
# Purpose: capture reproducible pre/post evidence for the pcie1 bring-up
# maintenance window (see ../PCIE_BRINGUP_RUNBOOK.md). Runs ON the RK3576
# board as the ordinary `kvdev` user.
#
# This script only READS system state. It must never load/unload modules,
# unbind/bind drivers, rescan the bus, touch /dev/mmcblk*, write a BAR,
# mount anything, or modify the device tree/DTB. Those actions belong to the
# approved maintenance runbook and the serial root shell, not here.
# tests/test_probe_tool.py enforces this read-only contract.
#
# Usage:
#   bash probe_enumeration.sh
#   bash probe_enumeration.sh /home/kvdev/work_pc2_pcie/evidence
set -u

OUT_DIR="${1:-}"
if [ -n "$OUT_DIR" ]; then
  mkdir -p "$OUT_DIR"
  LOG="$OUT_DIR/probe_enumeration_$(date -u +%Y%m%dT%H%M%SZ).log"
  exec > >(tee "$LOG") 2>&1
  echo "saving log to $LOG"
fi

section() { printf '\n===== %s =====\n' "$1"; }

section "identity"
echo "id: $(id)"
echo "host: $(hostname)"
echo "uname: $(uname -a)"
echo "pc_time_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
head -2 /etc/os-release 2>/dev/null || true

section "pci_devices"
if command -v lspci >/dev/null 2>&1; then
  lspci -nn 2>&1
  echo "--- tree ---"
  lspci -tv 2>&1
else
  echo "lspci: NOT INSTALLED (do not install)"
fi
echo "--- /sys/bus/pci/devices ---"
ls -l /sys/bus/pci/devices 2>&1

section "platform_pcie_drivers"
for drv in rk-pcie rockchip-pcie; do
  echo "--- driver $drv ---"
  ls -l "/sys/bus/platform/drivers/$drv" 2>&1
done
for phy in rockchip-pcie-phy rockchip-snps-pcie3-phy naneng-combphy; do
  echo "--- phy $phy ---"
  ls -l "/sys/bus/platform/drivers/$phy" 2>&1
done

section "device_nodes"
ls -l /dev/ANLOGIC* /dev/sgdma* 2>&1
echo "--- /dev/dri (NPU/display, reference only) ---"
ls -l /dev/dri/ 2>&1

section "dmesg_pcie"
dmesg 2>/dev/null | grep -iE 'pcie|anlogic|sgdma|dw-pcie|link up|link down' | tail -80 || true

section "device_tree_pcie"
for n in /proc/device-tree/pcie@*; do
  [ -e "$n" ] || continue
  echo "--- $n ---"
  printf 'status: '
  cat "$n/status" 2>/dev/null | tr -d '\0'
  echo
  printf 'compatible: '
  cat "$n/compatible" 2>/dev/null | tr '\0' ' '
  echo
  for p in num-lanes max-link-speed; do
    if [ -e "$n/$p" ]; then
      printf '%s: ' "$p"
      cat "$n/$p" 2>/dev/null | tr -d '\0'
      echo
    fi
  done
done

section "summary"
if [ -d /sys/bus/pci/devices ] && [ -n "$(ls -A /sys/bus/pci/devices 2>/dev/null)" ]; then
  echo "RESULT: PCI_ENUMERATED"
else
  echo "RESULT: NO_PCI_ENDPOINT"
fi

section "end"
echo "probe_enumeration complete"

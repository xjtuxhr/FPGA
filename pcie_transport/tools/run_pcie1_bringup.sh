#!/usr/bin/env bash
#
# One-shot PCIe1 bring-up (RUN AS ROOT ON THE SERIAL CONSOLE, ttyFIQ0).
# Enables pcie@2a210000 in the boot DTB and (optionally) reboots.
# Fail-closed: aborts on the first failure. Read PCIE_BRINGUP_RUNBOOK.md first.
#
# Usage (serial root shell):
#   bash /home/kvdev/work_pc2_pcie/run_pcie1_bringup.sh            # patch only
#   bash /home/kvdev/work_pc2_pcie/run_pcie1_bringup.sh --reboot   # patch + reboot
set -euo pipefail

BASE=/home/kvdev/work_pc2_pcie
PROBE="$BASE/probe_enumeration.sh"
PATCH="$BASE/patch_pcie1_dtb.py"

[ "$(id -u)" = "0" ] || { echo "STOP: run as root on the serial console (ttyFIQ0)"; exit 1; }
for f in "$PROBE" "$PATCH"; do
  [ -f "$f" ] || { echo "STOP: missing $f"; exit 1; }
done

echo "########## 1/4 pre-state (read-only) ##########"
bash "$PROBE" | sed -n '/===== summary =====/,$p' || true

echo "########## 2/4 patch dry-run ##########"
python3 "$PATCH" --check-only

echo "########## 3/4 apply patch (backup -> patch -> verify) ##########"
python3 "$PATCH"
sync

echo "########## 4/4 backup recorded ##########"
ls -1 /userdata/p3_dtb_backup_*.bin | tail -n 1
echo "ROLLBACK: dd if=<that backup> of=/dev/mmcblk0p3 bs=1M && sync && reboot"

if [ "${1:-}" = "--reboot" ]; then
  echo "########## rebooting now ##########"
  reboot
else
  echo "PATCH_OK_NO_REBOOT: re-run with --reboot (or run 'reboot') when ready"
fi

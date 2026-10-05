#!/usr/bin/env bash
#
# PCIe1 bring-up helper (RUN AS ROOT ON THE SERIAL CONSOLE, ttyFIQ0).
#
# IMPORTANT: /dev/mmcblk0p3 is a U-Boot FIT container, NOT a raw kernel DTB
# (see pcie_transport/PCIE_BRINGUP_RUNBOOK.md and VENDOR_PCIE_REFERENCE.md).
# The old patch_pcie1_dtb.py parsed the outer FIT and cannot patch pcie1.
#
# This helper is deliberately NON-DESTRUCTIVE in the current version:
# it only analyzes the FIT and prints the plan. The guarded in-place apply
# (backup + write + readback + kernel/resource unchanged verification) is the
# next version's `fit_dtb_patch.py --apply` and is NOT enabled here yet.
#
# Preferred vendor path: flash the vendor boot.img (its embedded DTB already
# has pcie@2a210000 = okay). See VENDOR_PCIE_REFERENCE.md.
set -euo pipefail

BASE=/home/kvdev/work_pc2_pcie
PROBE="$BASE/probe_enumeration.sh"
FIT="$BASE/fit_dtb_patch.py"

[ "$(id -u)" = "0" ] || { echo "STOP: run as root on the serial console (ttyFIQ0)"; exit 1; }
for f in "$PROBE" "$FIT"; do
  [ -f "$f" ] || { echo "STOP: missing $f (upload the revised files first)"; exit 1; }
done

echo "########## 1/2 pre-state (read-only) ##########"
bash "$PROBE" | sed -n '/===== summary =====/,$p' || true

echo "########## 2/2 FIT analysis of p3 (read-only) ##########"
python3 "$FIT" --fit /dev/mmcblk0p3 --check

echo
echo "STOP: analyze-only. In-place apply is not enabled in this version."
echo "Next: guarded apply (backup -> write -> readback -> kernel/resource unchanged)"
echo "or flash the vendor boot.img. Get both operators' approval first."

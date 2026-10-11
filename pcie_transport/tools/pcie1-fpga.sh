#!/bin/bash
# pcie1-fpga.sh - RK3576 PCIe1 (pcie@2a210000) + Anlogic FPGA bring-up.
#
# Reproduces the manually verified sequence:
#   power vcc3v3_pcie (gpio-124) -> pulse PERST# (gpio-48) -> (re)bind rk-pcie.
#
# Hardened 2026-10-11: the boot-time ordering race (rk-pcie trained before the
# FPGA/supply/PERST were ready) previously left lspci empty with no retry.
# This version retries the PERST# + bind sequence a bounded number of times.
#
# Idempotent: does nothing if the FPGA endpoint is already enumerated.
set -u

DRV=/sys/bus/platform/drivers/rk-pcie
GLOBAL_GPIO_VALUE_48=/sys/class/gpio/gpio48/value
GLOBAL_GPIO_VALUE_124=/sys/class/gpio/gpio124/value
MAX_ATTEMPTS=5

log() { echo "pcie1-fpga: $*"; }
enumerated() { lspci -nn 2>/dev/null | grep -q "1edb:abcd"; }

pulse_perst() {
    if [ -d /sys/class/gpio/gpio48 ]; then
        echo out > /sys/class/gpio/gpio48/direction 2>/dev/null || true
        echo 0   > "$GLOBAL_GPIO_VALUE_48" 2>/dev/null || true
        sleep 0.2
        echo 1   > "$GLOBAL_GPIO_VALUE_48" 2>/dev/null || true
        log "gpio-48 (PERST#) pulsed"
    fi
}

# 0) already enumerated -> nothing to do
if enumerated; then
    log "endpoint 1edb:abcd already enumerated; skip"
    exit 0
fi

# 1) 3.3V rail on gpio-124. It is claimed by the 'vcc3v3_pcie0' fixed
#    regulator (off, no consumer). Make it release the gpio, then drive high.
if [ ! -d /sys/class/gpio/gpio124 ]; then
    echo vcc3v3-pcie0 > /sys/bus/platform/drivers/reg-fixed-voltage/unbind 2>/dev/null || true
    echo 124 > /sys/class/gpio/export 2>/dev/null || true
fi
if [ -d /sys/class/gpio/gpio124 ]; then
    echo out > /sys/class/gpio/gpio124/direction 2>/dev/null || true
    echo 1   > "$GLOBAL_GPIO_VALUE_124" 2>/dev/null || true
    log "gpio-124 (vcc3v3_pcie) = high"
else
    log "WARN: could not take gpio-124"
fi

# 2) PERST# on gpio-48: assert low, then deassert high.
echo 48 > /sys/class/gpio/export 2>/dev/null || true
pulse_perst

# 3) (re)bind the controller with bounded retries for boot-time races.
attempt=0
while :; do
    if [ -d "$DRV/2a210000.pcie" ]; then
        echo 2a210000.pcie > "$DRV/unbind" 2>/dev/null || true
        sleep 1
    fi
    echo 2a210000.pcie > "$DRV/bind" 2>/dev/null || true
    sleep 3

    if enumerated; then
        log "PCIe1 up: $(lspci -nn | grep 1edb)"
        exit 0
    fi

    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
        log "PCIe1 NOT enumerated after ${MAX_ATTEMPTS} attempts; check 'dmesg | grep -i pcie'"
        exit 0
    fi
    log "retry ${attempt}/${MAX_ATTEMPTS}: re-pulsing PERST# and rebinding"
    pulse_perst
    sleep 2
done

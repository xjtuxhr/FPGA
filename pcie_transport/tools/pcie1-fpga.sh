#!/bin/bash
# pcie1-fpga.sh - RK3576 PCIe1 (pcie@2a210000) + Anlogic FPGA bring-up.
#
# Reproduces the manually verified sequence:
#   power vcc3v3_pcie (gpio-124) -> pulse PERST# (gpio-48) -> (re)bind rk-pcie.
#
# Hardened 2026-10-11: the boot-time ordering race (rk-pcie trained before the
# FPGA/supply/PERST were ready) previously left lspci empty with no retry.
#
# Hardened 2026-04-27 (PC2): a 5-attempt / 34 s boot window was still too short
# on cold boot -- the boot service logged retry 1/5..5/5 then gave up, while a
# manual unbind+run minutes later came up on the first try. This version:
#   * waits for the gpio/regulator subsystems, then an initial settle delay;
#   * retries the PERST# + bind sequence for a much longer bounded window;
#   * exits NON-ZERO on final failure so the systemd unit can Restart.
#
# Idempotent: does nothing if the FPGA endpoint is already enumerated.
set -u

DRV=/sys/bus/platform/drivers/rk-pcie
GLOBAL_GPIO_VALUE_48=/sys/class/gpio/gpio48/value
GLOBAL_GPIO_VALUE_124=/sys/class/gpio/gpio124/value
MAX_ATTEMPTS=45
INITIAL_DELAY=5
RETRY_SLEEP=4
SUBSYS_WAIT=30

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

# 0b) wait for the gpio + regulator subsystems, then settle.
i=0
while [ ! -d /sys/class/gpio ] && [ "$i" -lt "$SUBSYS_WAIT" ]; do
    sleep 1
    i=$((i + 1))
done
log "initial settle ${INITIAL_DELAY}s (subsys wait ${i}s)"
sleep "$INITIAL_DELAY"

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
        exit 1
    fi
    log "retry ${attempt}/${MAX_ATTEMPTS}: re-pulsing PERST# and rebinding"
    pulse_perst
    sleep "$RETRY_SLEEP"
done

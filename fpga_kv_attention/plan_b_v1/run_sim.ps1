param(
    [string]$Iverilog = 'E:\iverilog\bin\iverilog.exe',
    [string]$Vvp = 'E:\iverilog\bin\vvp.exe'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$old = Join-Path (Split-Path $here -Parent) 'plan_b_status'
$frozen = Join-Path (Split-Path $here -Parent) 'functional_b64s3\rtl'
$rtl = Get-ChildItem -LiteralPath $frozen -Filter '*.v' |
    Where-Object { $_.Name -notin @('v2_endpoint.v','v2_endpoint_cdc.v') } |
    ForEach-Object FullName
$out = Join-Path $env:TEMP "planb_v1_sim_$PID"
New-Item -ItemType Directory -Path $out -Force | Out-Null

function Run-Case([string]$name, [string]$top, [string]$cwd, [string[]]$sources, [string]$expected) {
    $binary = Join-Path $out "$name.out"
    & $Iverilog -g2005 -s $top -o $binary @sources
    if ($LASTEXITCODE -ne 0) { throw "$name compile failed" }
    Push-Location $cwd
    try {
        $result = (& $Vvp $binary | Out-String)
        if ($LASTEXITCODE -ne 0 -or -not $result.Contains($expected)) {
            throw "$name simulation failed: $result"
        }
        Write-Output "$name : $expected"
    } finally { Pop-Location }
}

Run-Case 'pc2_status' 'planb_status_ctrl_tb' $here @(
    "$here\rtl\planb_status_ctrl.v", "$here\sim\planb_status_ctrl_tb.v"
) 'ALL PLANB STATUS TESTS PASSED'
Run-Case 'planb_guard' 'planb_v1_tb' $here @(
    "$here\rtl\planb_status_ctrl.v", "$here\rtl\planb_reset_guard.v",
    "$here\sim\planb_v1_tb.v"
) 'planb_v1: ALL checks PASSED'
$common = @($rtl) + @(
    "$here\rtl\v2_endpoint.v", "$here\rtl\v2_endpoint_cdc.v"
)
Run-Case 'ready_gate' 'cdc_ready_gate_tb' $here ($common + @(
    "$here\sim\cdc_ready_gate_tb.v"
)) 'cdc_ready_gate: PASS'
Run-Case 'partial_frame_reset' 'partial_frame_reset_tb' $here ($common + @(
    "$here\rtl\planb_reset_guard.v", "$here\sim\partial_frame_reset_tb.v"
)) 'partial_frame_reset: PASS'
Run-Case 'reset_cdc' 'reset_cdc_tb' $old ($common + @(
    "$here\sim\reset_cdc_v1_tb.v"
)) 'reset_cdc: ALL 62 cases PASSED'

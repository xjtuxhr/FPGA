param(
    [string]$Iverilog = 'E:\iverilog\bin\iverilog.exe',
    [string]$Vvp = 'E:\iverilog\bin\vvp.exe'
)
$ErrorActionPreference = 'Stop'
$frozen = Join-Path (Split-Path $PSScriptRoot -Parent) 'functional_b64s3\rtl'
$rtl = Get-ChildItem -LiteralPath $frozen -Filter '*.v' |
    Where-Object { $_.Name -notin @('v2_endpoint.v','v2_endpoint_cdc.v') } |
    ForEach-Object FullName
$overlays = @(
    (Join-Path $PSScriptRoot 'rtl\v2_endpoint.v'),
    (Join-Path $PSScriptRoot 'rtl\v2_endpoint_cdc.v'),
    (Join-Path $PSScriptRoot 'rtl\kv_app_status.v')
)
$cases = @(
    @('kv_app_status_tb','kv_app_status: ALL checks PASSED'),
    @('planb_soft_reset_cdc_tb','planb_soft_reset_cdc: PASS'),
    @('reset_cdc_tb','reset_cdc: ALL 62 cases PASSED')
)
$tempDir = Join-Path $env:TEMP "planb_sim_$PID"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
Push-Location $PSScriptRoot
try {
    foreach ($case in $cases) {
        $top = $case[0]
        $tb = if ($top -eq 'reset_cdc_tb') { 'reset_cdc_planb_tb.v' } else { "$top.v" }
        $output = Join-Path $tempDir "$top.out"
        & $Iverilog -g2005 -s $top -o $output $rtl $overlays (Join-Path $PSScriptRoot "sim\$tb")
        if ($LASTEXITCODE -ne 0) { throw "Icarus compile failed: $top" }
        $result = (& $Vvp $output | Out-String)
        Write-Output $result
        if ($LASTEXITCODE -ne 0 -or -not $result.Contains($case[1])) {
            throw "Simulation failed: $top"
        }
    }
} finally {
    Pop-Location
    if ((Resolve-Path -LiteralPath $tempDir).Path.StartsWith((Resolve-Path -LiteralPath $env:TEMP).Path,
            [StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $tempDir -Recurse -Force
    }
}

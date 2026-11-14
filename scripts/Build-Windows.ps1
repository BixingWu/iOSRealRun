param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$PythonExe = (Get-Command -Name $Python -CommandType Application | Select-Object -First 1).Source
& $PythonExe -I (Join-Path $PSScriptRoot "build_portable.py")
exit $LASTEXITCODE

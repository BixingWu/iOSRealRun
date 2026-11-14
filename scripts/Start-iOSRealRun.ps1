param(
    [switch]$SkipMount,
    [switch]$SetupOnly,
    [switch]$Console,
    [string]$Python,
    [switch]$PauseOnError
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectDir ".pvenv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $ProjectDir "requirements.txt"
$DesktopMode = -not ($Console -or $SkipMount)

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

function Invoke-PythonProbe {
    param([string]$Executable, [string[]]$Arguments)

    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return
    }
    # Windows PowerShell can turn stderr from a broken launcher into an error record.
    $ErrorActionPreference = "Continue"
    $output = & $Executable @Arguments 2>$null
    if ($LASTEXITCODE -eq 0) {
        $output
    }
}

function Find-BasePython {
    # Keep the interpreter path intact across PowerShell 5.1 and Python code pages.
    $probe = "import base64, sys, sysconfig, venv, ensurepip; assert (3, 10) <= sys.version_info[:2] < (3, 15) and sysconfig.get_platform() in ('win-amd64', 'win-arm64'); print(base64.b64encode(sys._base_executable.encode('utf-8')).decode('ascii'))"
    $pythonDescription = "64-bit Python 3.10 to 3.14"
    $arguments = @("-I", "-c", $probe)

    if ($Python) {
        $executable = Invoke-PythonProbe $Python $arguments
        if (-not $executable) {
            throw "Cannot use '$Python'. Specify the path to a working $pythonDescription."
        }
    } else {
        $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
        if ($launcher) {
            foreach ($version in @("-3.12", "-3.11", "-3.13", "-3.10", "-3.14", "-3")) {
                $executable = Invoke-PythonProbe $launcher.Source (@($version) + $arguments)
                if ($executable) { break }
            }
        }

        if (-not $executable) {
            $systemPython = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue
            if ($systemPython -and $systemPython.Source -notlike "*\Microsoft\WindowsApps\python.exe") {
                $executable = Invoke-PythonProbe $systemPython.Source $arguments
            }
        }
    }

    if (-not $executable) {
        throw "No usable Python found. Install $pythonDescription from https://www.python.org/downloads/ or rerun with -Python and the full path to python.exe."
    }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($executable))
}

function Initialize-Environment {
    $lockPath = Join-Path $ProjectDir ".pvenv.lock"
    try {
        $setupLock = [System.IO.File]::Open($lockPath, "OpenOrCreate", "Write", "None")
    } catch [System.IO.IOException] {
        throw "Could not lock the project for setup. Close other setup windows and try again. $($_.Exception.Message)"
    }

    try {
        $oldEnvironment = Get-Item -LiteralPath $VenvDir -Force -ErrorAction SilentlyContinue
        if ($oldEnvironment -and (-not $oldEnvironment.PSIsContainer -or
            ($oldEnvironment.Attributes -band [System.IO.FileAttributes]::ReparsePoint))) {
            throw "Expected a regular virtual environment directory at '$VenvDir'."
        }

        $venvProbe = "import sys, sysconfig; assert sys.prefix != sys.base_prefix and (3, 10) <= sys.version_info[:2] < (3, 15) and sysconfig.get_platform() in ('win-amd64', 'win-arm64'); print(sys.version.split()[0])"
        $pythonVersion = Invoke-PythonProbe $PythonExe @("-I", "-c", $venvProbe)
        if (-not $pythonVersion) {
            $basePython = Find-BasePython
            if ($oldEnvironment) {
                $backupName = ".pvenv.broken-$([guid]::NewGuid().ToString('N'))"
                Rename-Item -LiteralPath $oldEnvironment.FullName -NewName $backupName
                Write-Host "Saved the old virtual environment as $backupName"
            }

            Write-Host "Creating .pvenv with $basePython"
            & $basePython -I -m venv $VenvDir
            if ($LASTEXITCODE -ne 0) {
                throw "Could not create .pvenv. Check the Python error above and retry."
            }
            $pythonVersion = Invoke-PythonProbe $PythonExe @("-I", "-c", $venvProbe)
            if (-not $pythonVersion) {
                throw "The new virtual environment's Python could not start."
            }
        }
        Write-Host "Python $pythonVersion ($PythonExe)"

        $stamp = Join-Path $VenvDir "requirements.sha256"
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            $requirementsHash = [Convert]::ToBase64String($sha256.ComputeHash([System.IO.File]::ReadAllBytes($Requirements)))
        } finally {
            $sha256.Dispose()
        }
        $installedHash = Get-Content -LiteralPath $stamp -ErrorAction SilentlyContinue
        $dependencyProbe = @'
import coloredlogs
import geopy.distance
import yaml
from importlib.metadata import version
from PySide6.QtWidgets import QApplication
from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.services.simulate_location import DtSimulateLocation

print(version('pymobiledevice3'))
'@
        $deviceLibraryVersion = Invoke-PythonProbe $PythonExe @("-I", "-c", $dependencyProbe)

        if ($installedHash -ne $requirementsHash -or -not $deviceLibraryVersion) {
            if (-not (Invoke-PythonProbe $PythonExe @("-I", "-m", "pip", "--version"))) {
                & $PythonExe -I -m ensurepip --upgrade
                if ($LASTEXITCODE -ne 0) {
                    throw "Could not install pip in .pvenv."
                }
            }
            Write-Host "Installing project dependencies..."
            & $PythonExe -I -m pip --disable-pip-version-check install -r $Requirements
            if ($LASTEXITCODE -ne 0) {
                throw "Could not install project dependencies. Check the pip error above and rerun with -SetupOnly."
            }
            & $PythonExe -I -m pip check
            if ($LASTEXITCODE -ne 0) {
                throw "The installed dependencies have conflicts. See the pip output above."
            }
            $deviceLibraryVersion = & $PythonExe -I -c $dependencyProbe
            if ($LASTEXITCODE -ne 0) {
                throw "Installed dependencies failed to load. Check the Python error above."
            }
            Set-Content -LiteralPath $stamp -Value $requirementsHash -Encoding Ascii
        } elseif ($SetupOnly) {
            & $PythonExe -I -m pip check
            if ($LASTEXITCODE -ne 0) {
                throw "The installed dependencies have conflicts. See the pip output above."
            }
        }

        Write-Host "pymobiledevice3 $deviceLibraryVersion"
    } finally {
        $setupLock.Dispose()
    }
}

$exitCode = 0
Push-Location -LiteralPath $ProjectDir
try {
    $env:PYTHONUTF8 = "1"
    Write-Host "iOSRealRun launcher"
    Write-Host "Project: $ProjectDir"
    Initialize-Environment

    if ($SetupOnly) {
        Write-Host "Setup complete. Double-click Start-iOSRealRun.bat to launch."
    } elseif ($DesktopMode) {
        & $PythonExe -m iosrealrun
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0 -and $PauseOnError) {
            Read-Host "Press Enter to close" | Out-Null
        }
    } elseif (-not (Test-IsAdmin)) {
        Write-Host "Requesting administrator access for the device tunnel..."
        $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"{0}"' -f $PSCommandPath), "-Console")
        if ($SkipMount) { $arguments += "-SkipMount" }
        if ($PauseOnError) { $arguments += "-PauseOnError" }
        $windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
        $child = Start-Process -FilePath $windowsPowerShell -ArgumentList $arguments -WorkingDirectory $ProjectDir -Verb RunAs -PassThru -Wait
        $exitCode = $child.ExitCode
    } else {
        Write-Host "Starting iOSRealRun. Use Ctrl+C in this window to stop."
        $appArguments = @("-m", "iosrealrun.main")
        if ($SkipMount) { $appArguments += "--skip-mount" }
        & $PythonExe @appArguments
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            Write-Host "iOSRealRun exited with code $exitCode." -ForegroundColor Red
            if ($PauseOnError) { Read-Host "Press Enter to close" | Out-Null }
        }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if ($PauseOnError) { Read-Host "Press Enter to close" | Out-Null }
    $exitCode = 1
} finally {
    Pop-Location
}
exit $exitCode

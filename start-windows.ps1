param([switch]$Demo)
$ErrorActionPreference = 'Stop'
$python = (Get-Command python -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) {
    throw 'Python with Tk and pythonw.exe is required (Python 3.12+ from python.org).'
}
$arguments = '"' + (Join-Path $PSScriptRoot 'windows_widget.py') + '"'
if ($Demo) { $arguments += ' --demo' }
Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden

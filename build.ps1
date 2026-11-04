param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --distpath portable --workpath build --name 'Piruleta Studio' --icon 'vendor/branding/piruleta.ico' --add-data 'vendor;vendor' --add-data 'program.html;.' --add-data 'README.md;.' launcher.py
if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar Piruleta Studio' }
Copy-Item -LiteralPath 'README.md' -Destination 'portable\Piruleta Studio\LEEME.md' -Force
Copy-Item -LiteralPath 'vendor\animations\CREDITOS.txt' -Destination 'portable\Piruleta Studio\CREDITOS.txt' -Force

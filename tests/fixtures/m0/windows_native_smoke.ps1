$ErrorActionPreference = 'Stop'
$temp = [IO.Path]::GetFullPath($env:TEMP)
$root = [IO.Path]::GetFullPath((Join-Path $temp 'review-writer-m0-pr-a-windows-smoke'))
if ((Split-Path -Parent $root) -ne $temp -or (Split-Path -Leaf $root) -ne 'review-writer-m0-pr-a-windows-smoke') { throw 'TEMP_CONTAINMENT_FAILED' }
New-Item -ItemType Directory -Force $root | Out-Null
$data = Join-Path $root 'data'; if (Test-Path -LiteralPath $data) { Remove-Item -LiteralPath $data -Recurse -Force }
$outside = Join-Path $root 'outside'; if (Test-Path -LiteralPath $outside) { Remove-Item -LiteralPath $outside -Recurse -Force }
$src = '\\wsl.localhost\Ubuntu\home\kenqia\my_folder\review-writer'
foreach ($item in @('review_writer\project\path_safety.py','schemas\project\project_manifest.schema.json','tests\fixtures\m0\synthetic\project.manifest.json')) {
  $to = Join-Path $root $item; New-Item -ItemType Directory -Force (Split-Path -Parent $to) | Out-Null; Copy-Item (Join-Path $src $item) $to -Force
}
$code = @'
import sys, subprocess
from pathlib import Path
root=Path(__file__).parent; sys.path.insert(0,str(root/'review_writer'/'project'))
from path_safety import PathSafetyError, validate_relative_path, validate_source_file
seed=root/'data'; (seed/'a').mkdir(parents=True,exist_ok=True); (seed/'a'/'x.txt').write_text('synthetic')
assert validate_source_file(seed,'a/x.txt').is_file()
for bad in ('C:/x','\\server\\share\\x','a\\x','a/../x'):
  try: validate_relative_path(bad); raise AssertionError(bad)
  except PathSafetyError: pass
assert 'a/x.txt'.casefold() == 'a/X.txt'.casefold()
outside=root/'outside'; outside.mkdir(exist_ok=True); (outside/'x.txt').write_text('synthetic')
junction=seed/'j'; subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],check=True,capture_output=True)
try: validate_source_file(seed,'j/x.txt'); raise AssertionError('escape')
except PathSafetyError: pass
(root/'windows-smoke-report.txt').write_text('PASS\n')
'@
Set-Content (Join-Path $root 'smoke.py') $code -Encoding utf8
py -3 (Join-Path $root 'smoke.py')
if ($LASTEXITCODE -ne 0) { throw 'WINDOWS_NATIVE_M0_PATH_SMOKE_FAILED' }
Write-Output 'WINDOWS_NATIVE_M0_PATH_SMOKE_PASS'

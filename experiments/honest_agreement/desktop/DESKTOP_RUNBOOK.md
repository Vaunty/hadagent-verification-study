# P-008 desktop runbook

**Current package: offline review bundle. Do not start desktop work yet.**
P-005b needs consensus. P-008 needs Matthew's approval, after the desktop specs
are recorded, and Claude's dated out-of-band confirmation. OpenCode must verify
the bundle. The official Python embeddable archive/digest is not on the laptop;
its lock entry is deliberately unresolved. Finalize that pin with a reviewed
bundle revision before this runbook's download step. No download was done to
prepare this package.

The proposed desktop budget is eight hours and fifteen scored phases including
calibrations. The desktop reference still uses one CPU thread; a fast GPU does
not establish its throughput. `P005b_PROPOSAL.md` holds the fixed design, cut
rule and cross-machine comparison. Do not edit the matrix after seeing scores.

All commands below are PowerShell. Use a folder outside OneDrive, for example
`C:\Research\P008`; no installer, admin, registry, permanent PATH, driver, CUDA
toolkit, Vulkan SDK, WSL, model conversion, pip or system changes are needed.
Transfer privately by USB or direct copy only after approval. No Git is needed
on the desktop. Never copy the original repo, `.env`, `.git` or the laptop venv.

## 1. Record specs, then complete the approval record

These read-only commands can run before approval:

```powershell
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
Get-Volume -DriveLetter C | Select-Object DriveLetter,SizeRemaining
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader }
```

Success: record the exact CPU, RTX 3060, existing driver, RAM and free bytes;
allow at least 20 GiB free as a preparation margin, not a measured requirement.
If the GPU/driver differs or disk is short, stop and report. Do not fix drivers
or silently select another CUDA family. The bundle fixes CUDA 12.4 and the two
original llama.cpp versions. Extra Intel graphics must not be used by mistake:
the preparation tool enumerates devices and requires exactly one RTX 3060
match for each GPU build before freezing a `--device` selector.

## 2. Verify the transferred ZIP before extracting

Copy the ZIP SHA and manifest SHA from Astra's outbox/OpenCode's independent
record, not from a file inside the ZIP. Paste them below. These placeholders
must be replaced with the reviewed values.

```powershell
$ZipPath = 'E:\desktop_bundle.zip'
$ExpectedZip = 'PASTE_REVIEWED_ZIP_SHA256'
$ManifestSha = 'PASTE_REVIEWED_MANIFEST_SHA256'
if ($ExpectedZip -notmatch '^[a-f0-9]{64}$' -or $ManifestSha -notmatch '^[a-f0-9]{64}$') { throw 'Paste reviewed hashes first' }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath).Hash.ToLower() -ne $ExpectedZip) { throw 'Bundle ZIP hash mismatch' }
if (Test-Path -LiteralPath 'C:\Research\P008') { throw 'Use a fresh destination; do not overwrite evidence' }
Expand-Archive -LiteralPath $ZipPath -DestinationPath 'C:\Research\P008'
Set-Location 'C:\Research\P008'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath '.\bundle-manifest.json').Hash.ToLower() -ne $ManifestSha) { throw 'Manifest mismatch' }
$BundleManifest = Get-Content -Raw '.\bundle-manifest.json' | ConvertFrom-Json
$VerifierHash = $BundleManifest.files.'verify_bundle.py'.sha256
if ((Get-FileHash -Algorithm SHA256 -LiteralPath '.\verify_bundle.py').Hash.ToLower() -ne $VerifierHash) { throw 'Verifier mismatch' }
```

Success: both hashes match. If either differs, stop; do not regenerate the
manifest to make it pass. Preserve the source ZIP for OpenCode.

## 3. Portable Python, without a venv installer

The reviewer's condition replaces the original "install Python / venv" step.
CPython's embeddable distribution is the isolated runtime; a venv and pip are
unnecessary. The package already contains the exact required dependencies in
`vendor/`, copied from the local environment and hashed individually. This is
recorded local provenance, not a fresh publisher verification of those wheels.
They target Windows AMD64 CPython 3.14. Use the pinned 3.14.4 runtime only.

The next commands deliberately fail until `downloads.lock.json` contains an
official python.org SHA-256 in a reviewed bundle revision. That revision also
records the official digest source; never paste a digest inferred from the
downloaded ZIP itself. This missing pin is preparation work, not authorization
to download an unverified runtime.

```powershell
$Lock = Get-Content -Raw '.\downloads.lock.json' | ConvertFrom-Json
$PythonPin = $Lock.python_runtime
if ($PythonPin.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Portable Python publisher pin is unresolved; stop for reviewed bundle revision' }
New-Item -ItemType Directory -Path '.\runtime' -ErrorAction Stop
Invoke-WebRequest -Uri $PythonPin.url -OutFile '.\runtime\python.zip'
if ((Get-FileHash -Algorithm SHA256 '.\runtime\python.zip').Hash.ToLower() -ne $PythonPin.sha256) { throw 'Python publisher hash mismatch; do not extract' }
Expand-Archive '.\runtime\python.zip' '.\runtime\python'
$Python = (Resolve-Path '.\runtime\python\python.exe').Path
& $Python -I -B '.\verify_bundle.py' --root . --expected-manifest-sha256 $ManifestSha --inventory
if ($LASTEXITCODE -ne 0) { throw 'Bundle verification failed' }
```

Success: verifier reports success and read-only hardware inventory. No system
PATH change is needed; `$Python` names the interpreter only in this terminal.
If native imports later fail, stop. Do not install alternate dependencies.

## 4. Save the authorization references and hardware

The references below must identify actual recorded decisions. These fields
prevent accidents; writing them does not create an approval. Keep this file
private on the desktop; it is excluded from the return package.

```powershell
New-Item -ItemType Directory -Path '.\state' -ErrorAction Stop
$Approval = @{
  p008_record = 'UNRESOLVED: dated RED approval including eight-hour desktop budget'
  p005b_record = 'UNRESOLVED: independent quorum and reviewer decision'
  matthew_out_of_band_record = 'UNRESOLVED: Claude dated confirmation'
  offline_bundle_review_record = 'UNRESOLVED: OpenCode bundle verification'
  runtime_review_record = 'UNRESOLVED: portable runtime pin and vendor review'
  desktop_specs_confirmed = $true
}
$Approval | ConvertTo-Json | Set-Content -Encoding UTF8 '.\state\authorization.json'
$Inventory = & $Python -I -B '.\verify_bundle.py' --root . --expected-manifest-sha256 $ManifestSha --inventory | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Verification failed' }
$Inventory.inventory | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 '.\state\hardware.json'
```

Replace the unresolved references with recorded decisions before running the
tools. Success: the hardware description contains CPU/GPU/driver/RAM/OS and
free disk, without hostname, username, serial numbers or network addresses.
On any mismatch against the approved machine, stop and report it.

## 5. Download and verify the fixed artifacts

```powershell
& $Python -I -B '.\prepare_artifacts.py' fetch --root . --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Download/pin check failed; stop' }
& $Python -I -B '.\prepare_artifacts.py' extract --root . --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Extraction failed; stop' }
& $Python -I -B '.\prepare_artifacts.py' inspect --root . --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Build/runtime/device check failed; stop' }
& $Python -I -B '.\launch.py' freeze --machine desktop --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Plan is not fully frozen; stop' }
```

Success: every archive/model matches its publisher digest; every extracted
EXE/DLL is hashed; the recorded version and required flags match; each GPU
build selects the RTX 3060; `state/` contains frozen plans with no unresolved
fields. `inspect` runs only version/help/device-list commands, not inference.
Nothing converts the FP16 model. Failed preparation stops; do not substitute
versions, precision, DLLs, runtime or driver. Keep all diagnostics local.

## 6. Main Q4 reference calibration, then the matrix

Before starting, close games and pause unrelated heavy workloads manually if
desired; do not change system settings. Check the power state and reserve an
uninterrupted eight-hour window. One persistent deadline starts here. It does
not reset when you reopen PowerShell. Each stage is single-use, even on failure.

```powershell
& $Python -I -B '.\launch.py' calibration --condition q4 --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Reference did not pass; STOP the study, preserve evidence' }
& $Python -I -B '.\launch.py' matrix --condition q4 --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Matrix incomplete or failed; STOP, do not retry' }
```

Success: complete reference, HadAgent-rule count within 15..85, then nine
planned Q4 rows. The controller freezes the observed calibration integer in a
new matrix plan; it never changes scientific inputs. The matrix reference must
equal it. A timeout, gate failure, reference mismatch, integrity error, or
uncertain process shutdown stops progression. No partial-score or accuracy
claim. Inspect server logs before asserting that the requested backend ran.

## 7. Separate FP16 and same-endpoint conditions

```powershell
& $Python -I -B '.\launch.py' calibration --condition fp16 --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'FP16 reference failed; stop' }
& $Python -I -B '.\launch.py' matrix --condition fp16 --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'FP16 condition failed; stop' }
& $Python -I -B '.\launch.py' calibration --condition load --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Load calibration failed or budget insufficient; stop' }
& $Python -I -B '.\launch.py' matrix --condition load --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Load condition failed or budget insufficient; stop' }
```

Success: separate FP16 output, then idle/loaded rows sharing one PID with
successful request overlap for every audit. The load phases are separate from
Q4 and FP16 matrix analyses. The controller refuses a stage if its full
allocation will not fit; leave it missing and report why. Never extend the
deadline, shorten the eval set or change the prompt to obtain completion.

## 8. Prepare and verify a private return copy

```powershell
& $Python -I -B '.\launch.py' export --expected-manifest-sha256 $ManifestSha
if ($LASTEXITCODE -ne 0) { throw 'Return-copy validation failed; preserve raw files locally' }
```

Success: `return/results.zip`, a return manifest hash and a ZIP hash. The copy
contains JSONL output hashes and analytical data, relative-path frozen plans,
summaries and the study ledger. It excludes raw logs, approval notes and full
inventories. Raw files stay unchanged on this machine. Review every returned
text file for personal identifiers before transferring; automated path checks
do not prove complete anonymization. If any remain, stop for a reviewed export
fix, not a hand-edited score or manifest.

Record both hashes separately. On return, check the ZIP hash before extraction
and use the original reviewed verifier with the return manifest hash:

```powershell
& $Python -I -B '.\verify_bundle.py' --root 'C:\Research\P008-return' --manifest 'C:\Research\P008-return\bundle-manifest.json' --expected-manifest-sha256 'PASTE_RETURN_MANIFEST_SHA256'
if ($LASTEXITCODE -ne 0) { throw 'Returned evidence hash mismatch' }
```

OpenCode reruns `analyze.py` separately against each returned condition's
unchanged plan hash. Keep original private logs available for local review;
they are not silently bundled. Any cross-machine script and claim gets an
independent check before use. Scope: one consumer NVIDIA GPU and two consumer
CPUs/iGPU; FP16 GGUF in llama.cpp, not the published BF16 data-center regime.

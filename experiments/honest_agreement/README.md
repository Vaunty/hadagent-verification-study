# P-005 honest-agreement experiment

**Status: offline preparation only.** Creating this directory did not download a model, dataset, or binary; contact a network service; start `llama-server`; or run a real inference. The candidate URLs below have not been opened or verified. Every value marked `UNRESOLVED` must stay unresolved until the project records the required P-005 approvals, then be checked against the publisher's current source before use.

This experiment asks whether nominally deterministic llama.cpp evaluations produce the same completion bytes and the same exact-match score under a fixed model, eval set, decode configuration, and selected runtime settings. It has two deliberately separate modes:

- `reexecution` represents the paper-described design in which a validator independently re-executes an evaluation. Each configuration and repeat gets a fresh local `llama-server` process. Every configuration must use `parallel: 1` and `load_workers: 0`.
- `same_endpoint_load` isolates behavior relevant to the current prototype, whose verifier re-queries the endpoint supplied in the payload. An idle pass and a pass under concurrent load use the same server process. This mode does not model independent validator re-execution.

Do not combine the modes in one plan, JSONL file, or report. Neither mode estimates a deployment false-positive rate, and neither can contradict the paper's reported 0% false-positive result. The analyzer reports a narrower quantity: output-hash agreement and the score-equality component that this prototype checks.

## Approval and machine boundary

Planning, stub tests, and static review are GREEN. Artifact retrieval, reference calibration with the real model, and the measured matrix require recorded P-005 approval and its conditions to be met. An `--approval-note` records an approval that already exists; it does not grant one. Matthew's approval is now recorded in the local outbox; this preparation task still follows the user's explicit no-download instruction.

The intended machine class is a consumer CPU with an integrated GPU. A resolved plan must record `cpu`, `gpu`, `driver`, `ram`, and `os` exactly as observed. Do not install a driver or Vulkan SDK, request administrator rights, change firewall rules, or accept a firewall prompt for this experiment. Bind only to `127.0.0.1`. If the approved llama.cpp build cannot use Vulkan as shipped, record the Vulkan cells as failed or missing and report that fact; do not repair the environment during the run.

## Candidate sources, still unresolved

These are candidate official project or publisher locations. The placeholders are part of the URL on purpose; no tag, asset name, revision, digest, or license has been verified offline.

| Artifact | Candidate URL | Required resolution after approval |
| --- | --- | --- |
| Qwen2.5-1.5B-Instruct GGUF | `https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/<UNRESOLVED_MODEL_REVISION>/qwen2.5-1.5b-instruct-q4_k_m.gguf` | Pin the immutable revision, verify the Hugging Face LFS SHA-256 and local file SHA-256, and verify the model-card license. Apache-2.0 is an expectation, not a verified fact. |
| MMLU code/source repository archive | `https://github.com/hendrycks/test/archive/<UNRESOLVED_MMLU_REVISION>.zip` | Treat this as candidate provenance only. Pin and hash it, then confirm whether it contains the required CSV data. If it does not, resolve and verify a separate official data-artifact URL and digest. The dataset license is pending verification. |
| MMLU data artifact, if separate | `<UNRESOLVED_MMLU_DATA_ARTIFACT_URL>` | Do not construct or guess this URL offline. Resolve its publisher, immutable revision, digest, contents, provenance, and license after approval. |
| llama.cpp version A, CPU asset | `https://github.com/ggml-org/llama.cpp/releases/download/<UNRESOLVED_LLAMA_CPP_TAG_A>/<UNRESOLVED_WINDOWS_CPU_AVX2_ASSET_A>` | Verify the release tag, exact archive asset, publisher-provided archive digest, extracted EXE and DLL hashes, license, CLI flags, and `--version` output. |
| llama.cpp version A, Vulkan asset | `https://github.com/ggml-org/llama.cpp/releases/download/<UNRESOLVED_LLAMA_CPP_TAG_A>/<UNRESOLVED_WINDOWS_VULKAN_ASSET_A>` | Perform the same archive and extracted-file checks, and retain server-log evidence before labeling the backend Vulkan. |
| llama.cpp version B, CPU asset | `https://github.com/ggml-org/llama.cpp/releases/download/<UNRESOLVED_LLAMA_CPP_TAG_B>/<UNRESOLVED_WINDOWS_CPU_AVX2_ASSET_B>` | Perform the same archive and extracted-file checks for the second predeclared version. |

Do not infer a pin from a moving branch, a release page, or a filename. For each llama.cpp configuration, `release_asset_sha256` is the publisher-verified digest of the downloaded archive, while `binary_sha256` is the independently computed SHA-256 of the extracted `llama-server` executable. Replace `runtime_files_sha256` with one relative-path-to-SHA-256 entry for every extracted DLL or other file the executable loads from that release. Verify the archive before extraction, then verify the EXE and runtime files before and after execution. `version_output_sha256` is the SHA-256 of the UTF-8 bytes of the combined `llama-server --version` output after leading and trailing whitespace is stripped. Configurations that use the same extracted build must carry the same hashes.

The example keeps all local artifacts under ignored paths: `tools/` for binaries and `experiments/honest_agreement/local/` for the model, eval set, logs, and results. No downloader is included.

Publisher verification of the release archive is an approval-time manual step. The runner checks the pinned local EXE, model, eval set, and runtime files before and after each session, and refuses an unpinned DLL in the release directory. Runtime paths are relative to the executable's directory. This does not hash Windows system libraries; the hardware/OS record describes that environment. Version output uses Python's universal-newline normalization before stripping and hashing. Rows record both Git HEAD and hashes of the runner, analyzer, scorer, and crypto source, so HEAD alone is not treated as proof of the code used.

## Fixed eval-set contract

The measured eval set contains exactly 100 items from the MMLU test split at one pinned revision. Freeze the following construction before calibration:

1. Enumerate the test-split subject CSV files and sort their relative paths lexicographically.
2. Traverse them round-robin by zero-based row index: row 0 from each subject in sorted order, then row 1 from each subject, continuing while skipping exhausted subjects.
3. Stop after exactly 100 rows. Do not shuffle, filter by model behavior, replace questions, or change the order after calibration.
4. Map the source label to one uppercase letter from `A`, `B`, `C`, or `D`. Serialize one UTF-8 JSON object per line with exactly the `prompt` and `answer` fields, preserve the selected order, and hash the final JSONL bytes.

Use this prompt template with its shown line breaks, then append one ASCII space after the final colon (and no final newline). The example JSON contains the exact template string:

```text
Question: {question}
A. {choice_a}
B. {choice_b}
C. {choice_c}
D. {choice_d}
Respond with exactly one uppercase letter: A, B, C, or D.
Answer:
```

The HadAgent scorer normalizes whitespace and case, then treats a completion as correct when it starts with the normalized answer. The runner also hashes the full raw and normalized completion text, so score equality and byte-for-byte output agreement remain separate measurements.

Record the pinned source, license result, selection rule, prompt template, and final JSONL SHA-256 in the resolved plan. A source or license string that still says `UNRESOLVED` is not evidence of verification.

## Reference calibration and stop gate

The example deliberately sets `preregistered_reference_correct` to `null`. A separate real-model calibration is still pending approval. After approval and supply-chain checks:

1. Resolve the hardware and artifact metadata without changing the prompt, 100-item selection, decode settings, reference configuration, matrix, or time budget. Save this frozen calibration plan with `preregistered_reference_correct: null`.
2. Run that plan once with `--execute --calibrate`. The runner scores only the first predeclared reference, writes one row with `calibration_only: true`, and stops before another configuration or a loaded phase.
3. If the count is below 15 or above 85, record it and stop. Do not tune the prompt or subset to move the score into range.
4. Preserve the calibration JSONL and its frozen plan. The analyzer reports the calibration-only stop reason and returns no agreement statistics.
5. If the count is in the inclusive 15..85 range, make a new matrix-plan copy, replace `null` with that integer, record the calibration artifact that supplied it, and preregister the matrix plan before execution. Do not overwrite the frozen calibration plan because its hash binds the pilot row.
6. During the matrix, the first emitted run must be the declared reference. Its score must equal the preregistered count; otherwise stop without retrying or choosing a replacement reference.

Every measured path requires `expected_items: 100`. The calibration path permits `preregistered_reference_correct: null`; measured matrix execution requires the observed calibration count as an integer. Synthetic unit tests use two items with a preregistered correct count of `1`, which passes the fixed 15..85% gate at 50%; that fixture does not weaken the measured-plan rules.

## Reexecution matrix and budget

[`plan.example.json`](plan.example.json) is the main `reexecution` plan. Its first configuration is the reference, and the runner emits configurations in array order and repeats in numeric order. The reference is therefore `cpu-vA-t1-b512-u128/repeat-0`.

The plan predeclares eight unique configurations and three repeats, for 24 planned runs:

- Version A CPU: 1, 4, 8, and 16 threads at batch 512 / ubatch 128.
- Version A CPU at 8 threads: batch 256 / ubatch 64 and batch 1024 / ubatch 256.
- Version A Vulkan at 8 threads, batch 512 / ubatch 128.
- Version B CPU at 8 threads, batch 512 / ubatch 128.

The wall-clock budget is six hours (`experiment_timeout_s: 21600`). Each process session has a 600-second deadline, with separate startup, request, and shutdown bounds. Do not extend a timeout or remove a slow cell after seeing results. A failed, interrupted, or missing run stays visible as such.

A watchdog stops the owned server at the earlier session or experiment deadline. Local hashing, process shutdown, and final log writes can finish after that deadline; no later session is started. Interrupted or failed sessions retain their rows, and unattempted rows remain missing. Preflight errors abort before any server starts and are reported by the CLI.

The backend field records the requested condition. It does not prove that the process used the CPU or Vulkan path. Preserve each server log and inspect it before making a backend claim. If the evidence is ambiguous, label the backend effective state as unverified.

## Same-endpoint idle/load plan

Create a separate plan for this condition; do not add it to the reexecution matrix. It must have:

- `mode: "same_endpoint_load"`;
- exactly one configuration;
- `parallel: 2` and `load_workers: 1` on that configuration;
- a fixed, preregistered `load_prompt`;
- the same model, eval set, decode settings, hardware record, repeat count, and integrity checks as the corresponding idle condition; and
- `reference_run_id` equal to `<id>/repeat-0/idle`.

For every repeat, the runtime starts one server process and emits `<id>/repeat-<r>/idle`, then `<id>/repeat-<r>/loaded`. Both rows must record the same server PID. The loaded phase is valid only when a successful background request overlaps every scored request; otherwise it fails. The first emitted row remains the only reference.

This condition tests one process serving an audit while it is busy. It does not test independent validator hardware, and it must not be presented as the paper's local reexecution design.

Use `same_instance_score_mismatch_fraction` for this paired condition: each loaded score is compared with its own session's idle score. The separate first-reference statistic also includes between-session comparisons. Recorded overlap is between client request intervals; it does not prove simultaneous GPU kernel execution. Calibrate and preregister this plan separately because its server uses a different parallel setting.

## Commands

From the repository root, this command validates the example's structure and prints the planned run IDs. It does not read artifacts or start a process:

```powershell
$env:PYTHONPATH = "hadagent/src"
.venv\Scripts\python -m experiments.honest_agreement.run --config experiments/honest_agreement/plan.example.json
```

The example cannot execute because its pins, digests, hardware record, and calibration score are unresolved. After the required approvals and verification, first preserve a frozen calibration-plan copy whose score remains `null`, then run the authorized pilot:

```powershell
$env:PYTHONPATH = "hadagent/src"
.venv\Scripts\python -m experiments.honest_agreement.run `
  --config experiments/honest_agreement/local/plan.calibration.json `
  --output experiments/honest_agreement/local/results/calibration.jsonl `
  --execute `
  --calibrate `
  --approval-note "<recorded P-005 and Matthew calibration approval reference>"
```

Analyze and retain that pilot against the same frozen calibration plan:

```powershell
$env:PYTHONPATH = "hadagent/src"
.venv\Scripts\python -m experiments.honest_agreement.analyze `
  experiments/honest_agreement/local/results/calibration.jsonl `
  --config experiments/honest_agreement/local/plan.calibration.json `
  --output experiments/honest_agreement/local/results/calibration.analysis.json
```

If the gate passes, copy the frozen plan to `plan.resolved.json`, set `preregistered_reference_correct` to the observed integer, record its calibration provenance, and freeze it. Then run the separately authorized matrix:

```powershell
$env:PYTHONPATH = "hadagent/src"
.venv\Scripts\python -m experiments.honest_agreement.run `
  --config experiments/honest_agreement/local/plan.resolved.json `
  --output experiments/honest_agreement/local/results/measured.jsonl `
  --execute `
  --approval-note "<recorded P-005 and Matthew approval reference>"
```

The analyzer interface must bind the report to the resolved plan with `--config`:

```powershell
$env:PYTHONPATH = "hadagent/src"
.venv\Scripts\python -m experiments.honest_agreement.analyze `
  experiments/honest_agreement/local/results/measured.jsonl `
  --config experiments/honest_agreement/local/plan.resolved.json `
  --output experiments/honest_agreement/local/results/analysis.json
```

The analyzer requires this `--config` option and rejects rows whose plan hash, planned run IDs, reference ID, mode, or invariant metadata differ from that plan.

## Reading the report

The predeclared first row is the reference. If it fails or is missing, analysis stops; it is never replaced. Comparisons exclude that reference from their denominator. Failed and missing runs are reported separately and do not silently become agreements or disagreements. A complete report needs every planned row.

Raw-output equality compares complete completion hashes. Score equality compares the integer exact-match total. Different outputs may receive the same score, and one score mismatch may arise from one or many changed item outputs. Within-configuration repeat stability should be read separately from comparisons to the reference.

Reject mixed model hashes, eval-set hashes, prompt sequences, decode settings, hardware metadata, code provenance, or conflicting binary identities. Report the tested settings and observed counts only. Do not generalize from this small, fixed matrix to other models, benchmarks, hardware, builds, or production false-positive rates.

Everything in this directory remains planned or stub-tested preparation. The matrix sizes, thresholds, timeouts, and configuration values are predeclared design choices, not measured model results. Required OpenCode and reviewer confirmation must be recorded before making any CRA, paper, or empirical claim from this work.

# P-005b: timing-only revision (AMBER, awaiting votes)

This is a proposed replacement schedule, not permission to execute. All counts,
limits, and matrix sizes below are **SIMULATED/planned design choices**, except the explicitly
labelled pilot observations. Nothing was downloaded or evaluated to prepare it.

The predeclared one-thread CPU reference calibration stopped at our harness's
fixed 600-second session limit after 50 of 100 items (MEASURED; independently
CONFIRMED by OpenCode in its 2026-10-08 evidence review).
The limit had been set without a throughput measurement. No HadAgent-rule score
was produced; per-item outputs were not recorded, so no partial score exists or
can be computed from the retained artifacts. The matrix was not started, and
nothing was retried or tuned. This re-plan uses timing evidence only.

The original attempt remains at commit
`74a87ea2263b38c7eb4c42fe358477649fad0a31`; its JSONL SHA-256 is
`cc0c4a3ed32d8a7e04db7a68680c44c6469c527e5732830ba1c8cfed0d869da5`.
See `MANIFEST_2026-10-08.md` and `docs/RESEARCH_LOG.md` for its command and
local evidence paths. The new calibration is a disclosed protocol amendment,
not a replacement presented as the original successful attempt.

## Frozen scientific inputs

Keep the exact Q4_K_M model bytes, eval JSONL and ordering, prompt template,
HadAgent DecodeConfig, seed, context, two builds, and reference identity
`cpu-vA-t1-b512-u128/repeat-0`. Keep the inclusive 15..85 HadAgent-rule score
gate. Keep startup/request/shutdown limits at 120/120/15 seconds.
No model, prompt, score gate, reference substitution, answer-based exclusion,
favorable retry, or further timeout adjustment is permitted after calibration.
An incomplete or out-of-gate calibration stops the study; a matrix reference
different from its registered calibration also stops it.

## Timing and fixed cuts

The pilot recorded 591.381844 scoring seconds for 50 completed prompts
(MEASURED, independently CONFIRMED). Linear extrapolation gives about 1,183 seconds
for the full set. Multiplying by 1.5 and rounding up gives a **1,800-second
session cap**, including startup. This is a planning estimate with a 50% safety
margin, not a throughput guarantee; the uncompleted half may be slower.

First reduce every cell from three repeats to one. Then remove the largest
thread-count condition (16) and largest batch condition (1024/256), preserving
the reference, the intermediate thread comparison, the smaller batch,
the backend comparison, and the older-build comparison. The resulting order is:

| Order | Build / backend | Threads | Batch / ubatch |
| --- | --- | --- | --- |
| Reference | A b11514 CPU | 1 | 512 / 128 |
| Next | A CPU | 4 | 512 / 128 |
| Next | A CPU | 8 | 512 / 128 |
| Next | A CPU | 8 | 256 / 64 |
| Next | A Vulkan | 8 | 512 / 128 |
| Last | B b11513 CPU | 8 | 512 / 128 |

One repeat cannot estimate within-configuration repeat stability. Any report
must say so. Preserve failed and missing rows and report their denominators.

Retain one separate same-endpoint pair on A CPU, 8 threads, batch 512/128,
two slots, one background worker. Its own idle calibration uses a single
1,800-second session; the actual idle/loaded session gets 3,600 seconds total.
The fixed benign load prompt is: `Write a short explanation of how rain forms.`
Use the same frozen model, eval set, and DecodeConfig. Successful client-request
overlap must cover every audit request; this is not evidence of GPU concurrency.
Do not pool this pair with the six-cell matrix.

## Shared six-hour budget

Charge the failed pilot 600 seconds. New inference caps sum to 18,000 seconds:
main calibration 1,800; six matrix sessions 10,800; load calibration 1,800;
one paired session 3,600. Reserve 300 seconds for ten sessions' cleanup (two
15-second waits each, including the old pilot), leaving 2,700 seconds for
hashing, checks, plan freezing, and operator overhead under 21,600 seconds.
The failed pilot's observed 0.031-second overrun is charged as well.

The revised study gets one persistent deadline, set at its first new calibration
to `start + (21600 - 600.0312538)` seconds. All later stages share it; reopening
a terminal does not reset it. Refuse a stage unless its full session allocation
and cleanup reserve fit. Run in this order: main calibration, matrix, optional
load calibration, optional pair. If insufficient time remains, omit the load
stage(s) and report them as budget-missing; never replace matrix cells with
faster ones. If the deadline interrupts the matrix, preserve its fixed order
and all remaining cells as missing. Cleanup and final evidence writes must
finish even if they overrun; record such overruns, never start more inference.

## Safeguards and review

GREEN code preparation adds failure-path integrity checks and a shared-budget
controller, exercised with stubs. No dependencies, downloads, driver changes,
or `hadagent/src` edits are needed for the revised laptop runs. Original files
stay untouched; revised plans/results use new paths. Every calibration or
matrix stage is single-use, including failures and interrupted invocations.
OpenCode verifies the code and retained pilot evidence; reviewer checks claims.
No paper or CRA result appears before independent confirmation.

This amendment stays inside Matthew's previously approved six-hour budget.
An increase would require a new RED approval confirmed out of band. Reversible:
discard the unexecuted revised plans; retain the failed pilot and proposal.

## Desktop alignment under P-008

P-008 waits for this amendment's decision. Its Q4 matrix starts with these same
six settings, then adds A CUDA, B CUDA, and B Vulkan at 8 threads, 512/128.
Each has one repeat. A separate A CUDA **FP16 GGUF in llama.cpp** condition has
its own calibration and one scored session; its model hash differs, so it is
never pooled into Q4 agreement. A separate A CUDA idle/load calibration and
one pair use the same rules as above. No local conversion or BF16 claim.

Propose a separate **eight-hour desktop budget** under the new RED P-008:
13 single sessions at 1,800 seconds plus one paired session at 3,600 seconds,
and 30 seconds cleanup for each of 14 sessions: 27,420 seconds, leaving 1,380
seconds overhead under 28,800. The cap is 15 scored phases including the
three calibrations (nine Q4 matrix, one FP16 matrix, two idle/load phases).
No desktop speed is assumed from its GPU; the shared reference is still a
one-thread Intel CPU run. Insufficient budget drops optional load stages first.

Analyze each machine and each model/condition separately. Predeclare only one
cross-machine comparison: corresponding Q4 repeat-0 rows for the common six
config IDs, using the revised laptop `cpu-vA-t1-b512-u128/repeat-0` as the fixed
cross-machine reference. Compare per-prompt raw/normalized output hashes and
integer HadAgent-rule score equality (both matched pairs and each row versus
that reference). Require equal model/eval/template/DecodeConfig, seed, context,
source hashes and intended configuration; record CPU/GPU and dispatched kernels
as differing factors. No pooled deployment false-positive rate, no FP16/Q4
pooling, no substitution if a matched cell or reference failed. Report matched
successful pairs out of six, with failed/missing pairs explicit. Cross-machine
analysis code must be independently checked before any such claim.

Scope: one consumer NVIDIA GPU and two consumer CPUs/iGPU. This is not the
published BF16 data-center experiment. Desktop specs, release/runtime pins,
offline bundle review, P-005b consensus and Matthew's P-008 out-of-band
confirmation remain execution gates.

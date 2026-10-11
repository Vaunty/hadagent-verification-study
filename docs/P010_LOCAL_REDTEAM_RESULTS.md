# P010 completed local adversarial evaluation

**Measured October 11, 2026; code and hypotheses frozen before execution at `a3990a30d198c90d357a83340da29dddabdff9a5`.** New AI-designed and AI-implemented work under Matthew Ngoy's direction. No retrospective claim of unaided student implementation or firsthand faculty assessment.

## Result

The unchanged local HadAgent block validator accepted a signed block naming the pinned Qwen model when a separate Python participant supplied known benchmark answers without executing that model. Four negative controls rejected for their expected reasons. The existing isolated score-arithmetic repair also accepted the known-answer participant in a standalone verifier call. Thus that repair addresses the prior score-rule issue but does not establish endpoint-to-model binding.

These are real local HTTP interactions, real signatures and block validation, and a real on-disk benchmark. The self-signed block and dishonest participant are constructed treatments. This is one controlled adversarial strategy under an explicit known-benchmark assumption, not six independent attacks or a statistical success-rate estimate. The MODEL and PROOF assert matching identifiers/hashes here; the prototype validates the records independently and does not cross-link those assertions to execution.

| Predeclared cell | First-run decision | Actual requests | Independent replica |
|---|---|---:|---|
| Known-answer participant, original block | Accepted | 100 | Same decision and count |
| Deliberately wrong answers | Rejected below threshold | 100 | Same decision and count |
| Incorrect score claim | Rejected claim mismatch | 100 | Same decision and count |
| Invalid producer signature | Rejected before HTTP | 0 | Same decision and count |
| Incorrect evaluation hash | Rejected before HTTP | 0 | Same decision and count |
| Known-answer participant, isolated fixed-scale verifier | Accepted | 100 | Same decision and count |

No HadAgent function, completion function, file loader, scorer, HTTP primitive, or block import was patched. Target source and the existing repair were unchanged. The current record-signature handling incorporates the authors' earlier fix; this experiment does not claim to discover it.

## Completed real-model reference

One reference run completed 100 actual inference requests using the cached Qwen2.5-1.5B-Instruct Q4_K_M model and pinned CPU llama.cpp b11514, four threads, with the frozen plain-completion prompts and decode configuration. The original scorer counted **28/100 normalized-prefix matches**. Scoring took **727.678236 seconds**; the whole first attempt took **763.460045 seconds**, including setup, the six cheap cells and integrity checks.

The response rule is a prefix test despite the helper's `score_exact_match` name. Only **1/100** normalized outputs was a bare A/B/C/D letter. Consequently this is a descriptive result for these exact raw completions, not standard MMLU accuracy or a fair estimate of Qwen capability. The reference called the scorer directly: it did not validate an honest block, measure false rejection, establish model identity cryptographically, or compare hardware.

All 100 responses were saved with their requests. An independent AI reviewer re-counted the matches after the run closed, verified all 100 HTTP 200 responses and equal upstream/returned response-body hashes, and checked 100 inference tasks in the llama log. That reviewer **did not rerun Qwen**. The benchmark requests matched the independent adversarial replica's request bodies. No latency advantage is inferred from different participant implementations.

The original P005 600-second failed calibration remains a separate failed experiment. It has not been overwritten, relabeled, or converted into this result. P010 used a separate predeclared objective and four-thread configuration; no score-based prompt/configuration search or favorable retry occurred.

## Reproduction and integrity

First command, from this worktree:

```text
C:\Users\matth\OneDrive\Desktop\RedTeamHarness\.venv\Scripts\python.exe -X utf8 experiments\local_redteam\run.py run --plan experiments\local_redteam\plan.json --output experiments\local_redteam\local\attempt-01
```

Independent execution used a clean detached worktree at the identical commit and appended `--adversarial-only`. Its output is `RedTeamHarness-verify-p010-20261011/experiments/local_redteam/local/independent-attempt-01`. Both processes exited 0. Source and artifact hashes remained stable, the owned evaluation fixture was removed, and both worktrees were clean at experiment completion. Port-specific signed bytes are recorded separately; different dynamic ports mean no cross-run byte-identity claim.

| Evidence | SHA-256 |
|---|---|
| Frozen plan | `dc4f7aed655a81249cee00dc36df441a04dd95ff3369f2f502fff33ceef169ce` |
| First final report | `8062b368ed70cad17e64a373296c4e5bcebdf09fe862a4c4e68203919f350884` |
| Independent replica report | `494014327166f1c2b2b876070545d81929875abab5cd66a138d294f5b12b2407` |
| Closed model-reference responses | `d3a642e3846c5fa8026c1bb80bb54d10e889ff5f3b07a429e5e64343fecedd55` |
| Independent review memo | `066483ce56674bcc574b69c4275a3b26d0479c6d9596cd3d5b4df194800f71d0` |
| Independent evidence manifest | `69ea8ad54adf8854e424512656d4b59675877a614523c828c6fd58688caabbee` |

The independent memo and sealed evidence live in `School_Work/Boyang_Survey/CRA_2026/Proposed_Revisions_2026-10-10/review_1000/`: `P010_INDEPENDENT_CHECK_2026-10-11.md`, `P010_INDEPENDENT_EVIDENCE_2026-10-11_a3990a3/`, and `P010_ROOT_CROSS_CHECK_2026-10-11.json`. The root cross-check additionally verified source/artifact invariance, record and producer signatures, lane roots, matching Qwen assertions, request order/configuration, independent prefix counts and semantic agreement across all six cells. This is supplementary native AI checking, not human validation or a fabricated vote by the project's designated providers.

The inherited suite passed **184 tests in 28.36 seconds** before P010 execution. Those tests use their own fixtures and are contextual regression evidence. Their synthetic summary metrics are not empirical estimates of the system's false-positive rate. The independent reviewer did not rerun that suite during P010.

## What changed and what remains

The work has progressed from mocked completions to a controlled local red-team experiment with a real model reference. It supports a concrete distinction: valid scored answers do not establish execution of the named model under the tested known-benchmark conditions. It extends an already-identified issue rather than supplying a new vulnerability class.

The snapshot's exact corresponding author revision remains unresolved. This run does not establish current upstream behavior, hidden/randomized challenge evasion, substitution between two real models, deployed-chain or peer acceptance, reward impact, prevalence, or cross-hardware false-rejection rates. The SoK remains unfinished and unsubmitted. The raw experimental method and artifacts stay out of the portable advisor packet; student-facing proposed text remains at the issue-class level and credits the new AI work.

For parallel Opus work, the highest-value tasks are source/version relevance, an argument connecting the observed behavior to the intended guarantee, and a preregistered next study with hidden challenges, genuine model substitution, and countermeasure tradeoffs. Boyang's own assessment of Matthew's reasoning is still essential. No paper, external message, merge, push, or submission was performed.

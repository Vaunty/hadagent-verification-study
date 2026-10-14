# P012 finite score-scale grid preregistration

**Status:** implementation and design prepared for root review; no experiment has run. Do not execute before the frozen commit is reviewed. Matthew authorized this bounded local quantification on October 11, 2026. A Codex AI agent designed and implemented it under his direction.

## Question and boundary

This experiment counts the copied original verifier's and the existing isolated fixed-scale repair's decisions across a complete five-item binary response grid. It runs from E5 results commit `069f6cce89e75bad32b8e969f7e3fe85dae6194e` in the separate branch `astra/metrics-grid-20261011`.

Every response and signed candidate is a **SIMULATED** fixture. The owned participant reads the five synthetic labels and returns a frozen binary pattern through actual loopback HTTP. It loads no model and uses no mock. If the study runs, only the decisions returned by the actual local `Block.validate` path are **MEASURED**. The result will not be an honest-real-model false-rejection rate, a confidence interval, a population estimate, or evidence about deployed systems.

Both arms use genuine record signatures, lane-root recomputation, producer signing, block serialization/deserialization, evaluation-file hashing and parsing, the copied normalized-prefix scorer, and ten actual loopback HTTP responses per paired candidate. The original target source remains unchanged on disk. For the modified arm only, the runner temporarily binds `podl_chain.block.verify_podl_llm_eval` to the exact existing `core.podl_verifier.verify_podl_llm_eval_fixed_scale` function object, calls the unmodified `Block.validate`, and restores the original imported reference in `finally`. Fresh deserializations of one immutable signed candidate go to both arms.

## Frozen finite cohorts

The eval file contains five unique prompt/answer pairs. A mask from `0` through `31` fixes which answers the lookup participant returns correctly, so Cohort 1 exhausts all 32 binary correctness patterns.

| Cohort | Candidates | Candidate scale and claim | Independent eligibility |
|---|---:|---|---|
| Canonical controls | 32 | `scale=10,000`; `claim=floor(correct*10,000/5)` | Six patterns have four or five correct and meet the 8,000 threshold; 26 do not |
| Defined inflation attempts | 78 | Each of the 26 below-threshold patterns at scales `20,000`, `40,000`, and `1,000,000`; `claim=floor(correct*scale/5)` | All 78 remain below threshold when accuracy and threshold use fixed 10,000 units |

This produces exactly 110 paired candidates, 220 validator decisions and 1,100 HTTP responses. Every candidate triggers five scorer requests in the original arm and five in the repaired arm.

## Independent oracle

The runner computes expected decisions without calling either verifier helper:

- `claim = floor(correct * candidate_scale / 5)`.
- Original expected acceptance requires that recomputed claim to be at least `8,000`.
- Repaired expected acceptance requires `claim == floor(correct * 10,000 / 5)` and `correct * 10,000 >= 8,000 * 5`.

The complete finite-count oracle is:

| Quantity | Predeclared count |
|---|---:|
| Canonical original accepts | 6 / 32 |
| Canonical repaired accepts | 6 / 32 |
| Eligible canonical repaired false rejects | 0 / 6 |
| Inflation original accepts | 70 / 78 |
| Inflation repaired accepts | 0 / 78 |
| Original accept to repaired reject within inflation cohort | 70 / 78 |

Counts must also be reported by correct-answer count and candidate scale. These are exhaustive counts for this synthetic finite cohort. The report must not attach confidence intervals or generalize them into real-world acceptance, exploit or error rates.

## Model-identity negative control

Mask `31` returns all five labels from the no-model lookup table. Its canonical signed claim is `10,000`. Both arms are expected to accept it. This result must remain visible because the arithmetic repair checks fixed score units; it does not establish which model computed answers or whether any model ran.

## Integrity and stopping rules

The runner refuses a dirty worktree, an output outside `experiments/score_scale_grid/local`, an existing output directory, an existing target eval fixture, a checkout that does not descend from the required E5 base, or an unexpected callsite function. It hashes target source, the repair, design, fixture and experiment code before and after execution. It creates the eval fixture only at the ignored path expected by the copied block validator, removes only its byte-identical owned copy, and records any mismatch or cleanup failure.

Any decision, reason, request count, prompt order or binary response pattern that differs from the frozen oracle stops the run and remains in a single-use attempt directory. No model, inference runtime, dependency, download, external endpoint, peer, ledger, consensus or reward path is involved.

## Review and later execution

Files for review:

- `experiments/score_scale_grid/run.py`
- `experiments/score_scale_grid/participant.py`
- `experiments/score_scale_grid/plan.json`
- `experiments/score_scale_grid/fixtures/evalset.jsonl`
- `core/podl_verifier.py` (existing repair; unchanged)
- `hadagent/src/podl_chain/block.py` and `pdl.py` (target; unchanged)

After root verifies the frozen commit and confirms that the separate baseline process is inactive, the intended command is:

```powershell
& '.venv\Scripts\python.exe' -X utf8 .\experiments\score_scale_grid\run.py --output .\experiments\score_scale_grid\local\attempt-01
```

That command is recorded for review. It has not been run.

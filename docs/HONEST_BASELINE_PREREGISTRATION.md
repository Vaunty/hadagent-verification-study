# Honest signed-block baseline preregistration

Status: implementation prepared for native source review. No model inference has run. The model phase may start only after Root reviews the frozen commit. Matthew's continuing instruction authorizes this bounded cached local study; the checks remain supplemental AI work rather than designated reviewer votes or human validation.

## Question

Can the pinned Qwen model produce a truthful score through the unchanged `pdl.score_exact_match` path and then reproduce that score when the unchanged `Block.validate` path evaluates a signed block after a fresh server start?

The study records three separate facts: score reproducibility, eligibility under the fixed 8000/10000 threshold, and the block decision. An honest model can truthfully fall below the threshold. Such a result is a legitimate below-threshold rejection, not evidence of model fraud.

## Frozen procedure

The runner uses the unchanged copied target at base `069f6cce89e75bad32b8e969f7e3fe85dae6194e`. It reuses the pinned local asset manifest at `experiments/local_redteam/plan.json`, SHA-256 `dc4f7aed655a81249cee00dc36df441a04dd95ff3369f2f502fff33ceef169ce`. It does not download, install, contact an API, or modify target code.

Phase one starts the cached Qwen2.5-1.5B-Instruct Q4_K_M model through pinned llama.cpp b11514 with four inference and batch threads, batch 512, ubatch 128, zero GPU layers, context 4096, one parallel slot and seed 42. A separate answer-blind proxy receives no evaluation path or labels. It forwards the original request-body bytes to the owned loopback model server and returns the original response-body bytes. Before returning each response, it writes and fsyncs raw request/response files plus a hash event. If an upstream body closes early, it preserves the partial bytes while separately recording the upstream status and returning HTTP 502. The unchanged `pdl.score_exact_match` and `DecodeConfig` make exactly 100 requests. Their scaled score becomes the truthful claim.

The runner then stops both proxy and model server and serializes one signed block containing the truthful claim, matching model/evaluation/configuration hashes and scale 10000. It fsyncs the candidate bytes and records their SHA-256 before starting phase two. Phase two starts a new model-server process with the same flags and a new answer-blind proxy bound to the same frozen loopback endpoint named by the signed proof. A bounded worker confirms the signed endpoint matches that owned endpoint, reads the exact frozen bytes and calls the unchanged `Block.validate(bytes(32), 0)`, which makes at most 100 new requests.

There are no retries, prompt edits, answer rewrites, threshold changes, scale changes or score gates. The fixed participant request is temperature 0.0, top-k 1, top-p 1.0 and 64 predicted tokens. The benchmark remains the known fixed 100-item MMLU subset; this is not a hidden-challenge experiment.

## Exact interpretation

The phase-two decision oracle depends on the measured validation score:

- If the validation score differs from the frozen claim, expect `claimed score mismatch`.
- If it matches and is below 8000, expect `score below target`.
- If it matches and is at least 8000, expect acceptance.
- Any infrastructure exception, timeout, incomplete trace or malformed response is a failed experiment, not a protocol rejection.

Both phases independently recount prefix matches using the target's exact `content or completion or empty string` response rule. The runner checks that all ordered request-body hashes match across phases. It reports generated-text equality per item separately from raw response-body equality because timing metadata may change even when generated text does not. Format compliance means the stripped output is exactly one uppercase A/B/C/D; it is diagnostic and does not replace the original prefix scorer.

The result register reports, for each phase, normalized-prefix matches out of 100, one-letter-compliant outputs out of 100, attempted/completed/successful HTTP requests, and wall time. It also reports the frozen claimed scaled score, the validation phase's independently recounted scaled score and their difference; paired exact-text, normalized-text and prefix-outcome agreement; and the validator's Boolean decision and exact reason. These are descriptive measurements from one fixed local run, not a false-positive/false-negative rate or a population stability estimate.

The signed block names the model and includes its measured local file hash. The experimenter verifies that file before execution, but the protocol still does not cryptographically prove which weights served the endpoint. A complete accepted run would establish one local honest baseline, not a false-rejection rate, model-attribution guarantee or cross-hardware result.

## Bounds and evidence

Each complete phase is capped at 1800 seconds, including startup and cleanup. The whole model run is capped at 3900 seconds. A frozen 100-second reserve precedes each phase/global deadline because the three nested owned-process contexts can each spend up to 30 seconds terminating and killing a surviving child. Model startup is capped at 120 seconds, proxy startup at 30 seconds, upstream requests at 115 seconds and target requests at their unchanged 120-second timeout. Scoring and validation occur in child processes. The proxy enforces 100 requests per phase and the report enforces 200 total.

Preflight requires at least 3 GiB available RAM and 200 MiB free output space. It hashes the model, benchmark, runtime and pinned runtime files; rejects an unpinned runtime DLL; verifies the runtime version output; requires a clean tracked worktree and absent evaluation fixture; and records platform and Python details. Output is exclusive and stays under the ignored local evidence directory. Source hashes are recorded before and after, the owned fixture is removed only if its final hash still matches, and partial logs remain on failure.

Dot's separate feasibility check already measured the five synthetic boundary controls: 5/5 expected decisions across 15 requests, with 52 asset hashes matched and no model inference. This runner does not repeat those cases. Its cheap tests prove that the proxy preserves arbitrary request/response bytes and has flushed evidence by the time the client receives the response; retains raw evidence on upstream failure; refuses model execution without `--execute-model`; and completes the full two-phase score/freeze/restart/validate orchestration against a label-blind local stub without loading a model.

## Review and execution commands

Cheap test:

```powershell
$env:PYTHONPATH='hadagent/src;.'
& '.venv\Scripts\python.exe' -m pytest -q tests/test_honest_baseline.py
```

Clean frozen preflight, with no model load:

```powershell
$env:PYTHONPATH='hadagent/src;.'
& '.venv\Scripts\python.exe' -B -X utf8 experiments/honest_baseline/run.py preflight --plan experiments/honest_baseline/plan.json --output experiments/honest_baseline/local/preflight-02 --expected-commit '<REVIEWED_COMMIT>'
```

The later reviewed model command is:

```powershell
$env:PYTHONPATH='hadagent/src;.'
& '.venv\Scripts\python.exe' -B -X utf8 experiments/honest_baseline/run.py run --plan experiments/honest_baseline/plan.json --output experiments/honest_baseline/local/attempt-01 --execute-model --expected-commit '<REVIEWED_COMMIT>'
```

The final command remains prohibited until the frozen commit passes Root's source review.

# Application guide

This guide covers the repository's tests, synthetic demonstrations, and recorded local experiments. Those are different activities. Running the unit suite checks implementation behavior; it does not reproduce an experimental result. Running `runner.py` produces illustrative fixture-based output; it does not measure a model or the HadAgent network. The P010 and P013 workflows require pinned local assets that are deliberately excluded from Git.

## Install

Use Python 3.10 or later from the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

The copied prototype is not packaged as an installed distribution, so commands that import `podl_chain` need its source directory on `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "hadagent/src"
```

No API key is needed for the test suite or local experiment runners. The optional OpenAI-backed safety judge in the older demonstration path reads `OPENAI_API_KEY` from a local `.env` file. Never commit that file.

## Run the regression suite

```powershell
$env:PYTHONPATH = "hadagent/src"
python -m pytest -q
```

The combined suite covers the copied record, block, ledger, pool, hub, and verifier code; the separate `core/poi` simulation; experiment orchestration; and evidence-integrity guards. Some experiment tests intentionally start loopback HTTP or TCP services. They do not contact external endpoints or run a language model.

## Reproduce the P012 synthetic score-scale grid

P012 is the smallest complete experiment that ships with all required fixtures. It enumerates five-answer response patterns across canonical and noncanonical score scales and evaluates the same signed candidate through the original and isolated-repair arms.

Read the [preregistration](P012_SCORE_SCALE_GRID_PREREGISTRATION.md) and [result record](P012_SCORE_SCALE_GRID_RESULTS.md) first. Then run:

```powershell
$env:PYTHONPATH = "hadagent/src"
python -m experiments.score_scale_grid.run `
  --output experiments/score_scale_grid/local/attempt-01
```

The output directory is ignored. The participant serves constructed labels over loopback HTTP; no model executes. A successful run should be compared with the preregistered per-cell oracles, not summarized as an attack rate against deployed systems.

## Inspect the P010 implementation boundary

`experiments/local_redteam/` contains three related runners:

- `run.py` tests a known-answer participant, negative controls, and an optional real-model reference.
- `extensions.py` tests metadata consistency, proof reuse, endpoint response changes, and a changed challenge at the direct block-validation boundary.
- `ledger_peer.py` extends those checks to the local file-backed ledger and loopback TCP hub.

The corresponding records are [P010 results](P010_LOCAL_REDTEAM_RESULTS.md), [HTTP extension results](LOCAL_HTTP_EXTENSION_RESULTS.md), and [ledger/peer results](LOCAL_LEDGER_PEER_RESULTS.md). The tracked plan uses repository-relative paths, but the model, runtime, evaluation source, and private evidence directories are not bundled. Verify every recorded digest before running. Do not substitute a newer model or runtime and call it a reproduction.

The adversarial-only portion uses a constructed known-answer participant. The optional reference uses the pinned local model. Neither path implements the paper's independent-master design, and a local ledger append is not network consensus.

## Inspect the P013 honest baseline

P013 starts a fresh local model server for a claim phase, freezes a signed block, starts another fresh server for validation, and compares the two phases. Its answer-blind proxy forwards request and response bytes without benchmark labels.

Read the [preregistration](HONEST_BASELINE_PREREGISTRATION.md) and [result record](HONEST_BASELINE_RESULTS.md). The tracked plan records expected hashes and the portable asset layout; the large assets and completed evidence are excluded. A run requires the exact pinned files, sufficient memory, a clean worktree, and explicit execution flags enforced by the runner.

The recorded block was truthfully below the eligibility threshold and was correctly rejected. Because there were no eligible honest acceptance trials, P013 does not estimate false rejection. Its two local phases also do not prove fresh prover-side computation or reproduce the paper's independent master-node verifier.

## Review the P005 calibration harness

`experiments/honest_agreement/` is a separately designed cross-configuration harness. Its one authorized calibration attempt did not finish the 100-item reference within the 600-second deadline. The full matrix was never run. See its [README](../experiments/honest_agreement/README.md) before using the dry-run interface.

P013 later completed a different two-phase baseline. It does not retroactively turn P005 into a completed experiment.

## Run the older synthetic demonstrations

The top-level dispatcher exercises a separate simulation under `core/poi/`:

```powershell
$env:PYTHONPATH = "."
python runner.py --attack all
```

Individual names are `determinism`, `trust-then-betray`, `model-binding`, `reproducibility`, and `validation-fuzzing`. These runners use constructed scores, outputs, trust transitions, or records. Their percentages and savings estimates are fixture properties unless a result document explicitly says otherwise. The trust, serving, anomaly, and defense classes in `core/poi/` are project simulations rather than copied HadAgent modules.

The safety-judge variants can make external API calls when explicitly enabled and configured. They are not needed for the measured P012 or P013 findings.

## Reports and local artifacts

The legacy dispatcher can generate a Markdown report from its local SQLite data:

```powershell
python report.py --poi
```

That report summarizes the older runner data. It does not aggregate P010, P012, or P013 evidence. The research experiments write structured JSON or JSONL into ignored `local/` or `test_results/` directories and record their artifact hashes in the corresponding result documents.

## Evidence interpretation

Use these rules when quoting the repository:

1. Name the exact experiment and boundary.
2. State whether inputs and participant behavior were synthetic or model-generated.
3. Treat validator decisions as measured only when the result record says the path executed.
4. Keep tests, requests, candidates, decisions, and independent trials as separate denominators.
5. Describe AI reproductions and audits as AI work, not independent human validation.
6. Do not generalize local loopback results to deployed consensus, rewards, prevalence, or current upstream code.

The [scope and claims note](SCOPE_AND_CLAIMS.md) maps these boundaries to exact copied functions and to the HadAgent paper's intended verifier design.

## Troubleshooting

- **`ModuleNotFoundError: podl_chain`**: set `$env:PYTHONPATH = "hadagent/src"` from the repository root.
- **Integrity guard reports a dirty tree**: commit or set aside unrelated tracked changes before running an evidence-producing experiment. Do not bypass the guard for a reported result.
- **Missing model, eval set, or runtime**: the large pinned assets are intentionally absent. Obtain the exact recorded revision and verify its digest; do not silently replace it.
- **Port already in use**: stop the conflicting local process or let a runner choose an available dynamic loopback port when supported.
- **P005 example will not execute**: that is intentional. `plan.example.json` contains unresolved pins and is suitable only for structural dry runs.
- **API error in a legacy defended run**: only that optional path needs an external judge key. The primary local validation studies do not.

Use these tools only on systems and endpoints you own or are authorized to evaluate.

# P005 honest-agreement calibration harness

This directory preserves the P005 harness for comparing one fixed model and evaluation set across declared local execution configurations. P005 did not complete its calibration gate, and the planned matrix was never run. It must not be cited as a measured determinism or false-rejection result.

## Preserved outcome

The one authorized calibration attempt started the pinned Qwen2.5-1.5B-Instruct Q4_K_M model under CPU llama.cpp and completed 50 of 100 benchmark requests before the frozen 600-second deadline. It stopped without producing a completed reference score. Because the preregistered reference was incomplete, the cross-configuration matrix remained gated and no agreement rate was computed.

The failure is retained as evidence rather than rewritten as a partial success. It establishes only that this exact calibration configuration did not complete within the declared deadline on the recorded machine.

P013 later completed a separate two-phase baseline using a different predeclared configuration. Its result is recorded in [Honest baseline results](../../docs/HONEST_BASELINE_RESULTS.md). P013 does not repair, replace, or retrospectively complete P005.

## Intended comparison

The harness separates two questions:

- **Cross-configuration agreement:** does the same fixed task, artifact, prompt sequence, and decode contract produce the same outputs and score under each declared backend or execution configuration?
- **Same-endpoint load pairing:** does one server process return the same score while idle and while a background request overlaps scored requests?

The second condition tests a busy server instance. It is not independent verifier hardware and does not implement the HadAgent paper's master-node recomputation design. Client-request overlap also does not prove simultaneous accelerator-kernel execution.

The analysis code distinguishes raw-output equality from score equality. Different outputs can receive the same aggregate score. Failed, interrupted, and missing runs remain outside the agreement denominator and are reported separately.

## Dry-run interface

The tracked example plan contains unresolved pins and cannot authorize execution. It can be parsed to inspect the planned run IDs without reading model assets or starting a process:

```powershell
$env:PYTHONPATH = "hadagent/src"
python -m experiments.honest_agreement.run `
  --config experiments/honest_agreement/plan.example.json
```

An evidence-producing run requires a separate resolved plan with verified artifact hashes, hardware metadata, a frozen reference, sufficient resources, and explicit authorization. Local plans, weights, runtimes, evaluation copies, and outputs belong under `experiments/honest_agreement/local/`, which Git ignores.

The analyzer binds rows to the supplied plan and rejects mismatched plan hashes, run IDs, reference IDs, modes, or invariant metadata:

```powershell
$env:PYTHONPATH = "hadagent/src"
python -m experiments.honest_agreement.analyze `
  experiments/honest_agreement/local/results/measured.jsonl `
  --config experiments/honest_agreement/local/plan.resolved.json `
  --output experiments/honest_agreement/local/results/analysis.json
```

Do not generalize a future small fixed matrix to other models, benchmarks, hardware, runtimes, or production false-positive rates. Report the tested configurations and observed denominators directly.

## Source and evidence boundary

- `run.py` orchestrates frozen configurations and evidence capture.
- `analyze.py` verifies plan binding, coverage, output hashes, score agreement, and paired-load results.
- `plan.example.json` documents the schema and is intentionally non-executable.
- `manifest.json` inventories the tracked harness files.

The harness was implemented and reviewed with AI agents under Matthew Ngoy's direction. Any completed run needs its own result record and attribution. The copied `podl_chain` verifier and the paper's intended master-node design remain distinct; see [Scope and claims](../../docs/SCOPE_AND_CLAIMS.md).

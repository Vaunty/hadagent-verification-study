# Research log: Red-teaming Proof-of-Inference in HadAgent

Matthew K. Ngoy. Mentor: Boyang Li. Kean University, Fall 2026.

Tracking document requested at the September 4 kickoff meeting: meeting notes,
the planned timeline, and progress updates. Where a period has no progress,
that is stated plainly.

## Meeting notes

### 2026-09-04, kickoff (Zoom, group)

Led by Boyang Li, with students from several universities.

Four research directions were presented:
1. Replacing Bitcoin's hash algorithm with deep learning so mining compute goes
   to useful work such as LLM inference. (This one is nearing completion; prior
   work on inference agents is published. I chose this direction.)
2. Machine unlearning in LLMs and diffusion models.
3. LLM safety and hallucination, attack and defense.
4. Agentic AI reliability and security.

Expectations Boyang set:
- Pick a topic that grows into a coherent line of work, not a one-off.
- Aim to submit a paper by the end of this semester or early next.
- Bi-weekly updates are the baseline; three weeks with no update is a red flag.
- Each student keeps a document with meeting notes, timeline, and progress, and
  states explicitly when a two-week period had no progress.

My action items: maintain this document; select a direction and send write-ups.

### 2026-09-14, Slack

I joined the lab Slack today and messaged Boyang that I would send my write-ups
and direction for the blockchain research this afternoon, and asked whether he
preferred email, direct message, or a channel. He replied "Great!".

The same day, Boyang posted in the group channel that after the first-week
meeting he had not received any updates in the second week, and that at this
point students are expected to select a direction to work on and start from the
given projects by reading existing papers or tech blogs.

So as of today I am behind on the reporting cadence. This log and the write-up I
am sending are my first update.

## Status as of 2026-09-14

Direction is selected: red-teaming HadAgent's Proof-of-Inference consensus for
correctness and safety. Proposal written (`Red_Team_HadAgent_POI_Proposal.pdf`).

Done:
- Read the HadAgent paper, slide deck, and the prototype source and git history.
- Confirmed the prototype is the consensus core only; the anomaly detector,
  trust manager, and two-tier serving in the paper are not in the code.
- Confirmed the tuple validation bug in the repo history (commits `1a8d490` to
  `a4ec9da`) and reproduced it in `runners/validation_fuzzing.py`.
- Noted that `pdl.py` verifies proofs against the endpoint URL in the miner's
  own record, and that the evalset `block.py` references is missing from the repo.
- Built harness scaffolding: `core/poi/` and five attack runners that execute;
  unit tests pass.

Not done / honest caveats:
- No real model inference has run. Every runner uses simulated or hardcoded
  scores, so no attack number is measured yet. README and THREAT_MODEL label
  which figures are placeholders.
- The validation fuzzer uses hand-written cases, not Hypothesis yet.
- I had not sent Boyang an update before today.

## Planned timeline (from the proposal)

These dates are the proposal's plan. I am starting the reporting later than the
plan assumes, so early rows overlap with catching up.

| Weeks | Dates | Primary deliverable |
|---|---|---|
| 1-2 | Sep 1 - Sep 11 | Read HadAgent; threat-model extension; scaffold harness and judge |
| 3-4 | Sep 14 - Sep 25 | Property-based test suite; reproduce the tuple bug before and after the fix |
| 5-6 | Sep 28 - Oct 9 | Reproducibility-is-not-safety demonstration; lookup-table / model-swap audit evasion |
| 7-8 | Oct 12 - Oct 23 | Determinism attack: score divergence across quantization, threads, library versions |
| 9-10 | Oct 26 - Nov 6 | Trust-then-betray on the minimal two-tier serving harness |
| 11-12 | Nov 9 - Nov 20 | Defenses: safety judge in the verification path; stretch: real-request auditing |
| 13-14 | Nov 23 - Dec 4 | Paper draft, reproducible artifact, poster |
| 15-16 | Dec 7 - Dec 21 | Final report and advisor sign-off |

## Next (Sep 14 - Sep 25)

- Convert one attack from simulated to measured: run the reproducibility runner
  with the safety judge actually calling the API for a real before/after number.
- Measure real score divergence: Llama-3.2-3B via llama.cpp at two quantizations.
- Move the validation fuzzer to Hypothesis and pin it against the buggy commit.

Progress: (to be filled in at the next update)

## 2026-10-08: score-scale unit reproduction (internal only)

The earlier gap in this log remains a gap; no measured experiment was recorded
here during that period. The hand reproduction documented in the survey's
`research/02_score_scale_bypass_CONFIRMED.md` on 2026-10-02 is now a repeatable
test in `tests/test_podl_score_scale.py` on `astra/real-verifier`. It calls the
real `podl_chain.pdl.verify_podl_llm_eval` with stubbed eval-set loading, parsing,
and scoring. HadAgent's source is unchanged, both hash checks execute, and an
HTTP guard fails the test if it tries to make a request.

SIMULATED inputs: an eval set of 100 synthetic pairs, threshold 8,000, and the
correct counts, scales, and matching claims below. MEASURED outputs: the real
verifier's decisions, asserted by the committed test. No model inference,
record validation, or chain acceptance was exercised.

| Correct / total (SIMULATED) | Scale (SIMULATED) | Claimed score (SIMULATED) | Verifier decision (MEASURED) |
|---|---|---|---|
| 85 / 100 | 10,000 | 8,500 | accept |
| 10 / 100 | 10,000 | 1,000 | reject: below target |
| 1 / 100 | 1,000,000 | 10,000 | accept: current score-scale bug |
| 0 / 100 | 1,000,000 | 0 | reject: below target |

MEASURED validation at commit `9753f8a95ee979ed17dae709953a40e74d4f7431`:
the full suite passed with `41 passed, 1 skipped`; this includes every case
above. The skip is from the untracked local `legacy/` test. OpenCode's clean
checkout gave MEASURED `41 passed` with no skip, recorded in
`.agents/work/opencode/task1_9753f8a_full_suite.txt`; its commands and evidence
are in `.agents/work/opencode/verification_log.md`. Astra's command from the
repository root:

```powershell
$env:PYTHONPATH='hadagent/src'
.venv\Scripts\python -m pytest -v 2>&1 | Tee-Object -FilePath 'test_results/astra-score-scale/full-suite-9753f8a.txt'
```

The output is saved locally at
`test_results/astra-score-scale/full-suite-9753f8a.txt` (ignored by Git).
The suite's existing validation-metrics section describes synthetic record
fixtures; its false-positive figure does not measure GPU nondeterminism or
honest-model behavior. OpenCode posted CONFIRMED on 2026-10-08 at 14:22.
At 14:30 that day, reviewer approved the claim's wording with three edits,
now applied: the source reference, skip clarification, and reviewer/confirmation
status are recorded here. P-002 has cleared for the endpoint test and proposed
fix, subject to the recorded conditions. Astra has
not pushed or shared the branch. External use remains blocked by P-003.

## 2026-10-08: endpoint test and proposed scale fix (P-002, internal only)

P-002 cleared with reviewer's conditions. The implementation is on
`astra/real-verifier`, commit `3886e2489fd7ebf6f7bf4b8ab30f43fbcd2efb29`.
HadAgent's source and block-validation path remain unchanged. OpenCode posted
CONFIRMED for the scoped tests on 2026-10-08 at 14:57. Reviewer approved the
wording with edits at 15:20; those edits are now applied, including the choice
to retain the tested copy and state explicitly that it ignores the payload's
scale in its arithmetic. External use remains blocked by P-003.

`tests/test_podl_endpoint_trust.py` constructs a lookup table from a synthetic
eval set inside the test and replaces only `urllib.request.urlopen`. The real
file loader, parser, request builder, scorer, and original verifier execute.
SIMULATED inputs: 5 prompt/answer pairs, payload scale 10,000, threshold 8,000,
and matching claims of 10,000 for table answers or 0 for deliberately wrong
answers. MEASURED: the unmodified verifier sends every audit prompt to the
endpoint URL taken from the prover's payload and accepts the full-score claim
when that endpoint answers from the lookup table. It rejects the wrong-answer
control. Each run checks the payload-supplied URL, request body, and complete
prompt sequence. No network request, server process, real benchmark answer
key, or model is involved.

Code inspection at the implementation commit explains the trust issue:
`hadagent/src/podl_chain/model.py:115` loads the eval-set JSONL in the helper
used by miners, hashes those bytes, and parses prompt/answer pairs; the parser
reads the answer field at `model.py:76`. The verifier hash-checks its eval-set
bytes at `pdl.py:92` and passes `payload_obj["endpoint"]` to the scorer at
`pdl.py:108`. Thus the prototype's miner helper has the answer-bearing eval
set, and this verification function checks responses from a prover-chosen
endpoint without binding them to the committed model. This finding concerns
that check; it does not establish that lookup tables are generally undetectable.

`core/podl_verifier.py` contains a proposed patched copy with a fixed reference
scale of 10,000 (a SIMULATED setting in these tests). It interprets
claims in those same units and requires
`correct * PROTOCOL_SCORE_SCALE >= threshold * total`. It still parses the
payload's scale to preserve input errors, but ignores the payload's scale in
the arithmetic. It does not reject a scale different from its fixed reference:
with SIMULATED inputs
of 85 correct out of 100, payload scale 1,000,000, and canonical claim 8,500,
the copy accepts (MEASURED). The payload can therefore declare a scale different
from the units used to interpret its claim. Strict rejection is an alternative
design, not implemented or measured here. This is a proposal for the authors;
it is not an upstream fix.

The SIMULATED threshold of 8,000 is interpreted in 10,000 units. Code inspection
supports that choice: `block.py:120` sets the threshold, `model.py:108` defaults
the miner helper's scale, and `demo_build_validate.py:101` uses the same scale
(all under `hadagent/src/podl_chain` at the implementation commit). The proposed
copy codifies that default; the original verifier does not enforce it.
`tests/test_podl_fixed_scale.py` compares the original and patched functions
on identical SIMULATED inputs and asserts the MEASURED decisions below.
The SIMULATED eval-set size is 100 and the fixture threshold is 8,000.

| Correct (SIMULATED) | Payload scale (SIMULATED) | Claim (SIMULATED) | Original decision (MEASURED) | Patched-copy decision (MEASURED) |
|---|---|---|---|---|
| 85 | 10,000 | 8,500 | accept | accept |
| 10 | 10,000 | 1,000 | reject: below target | reject: below target |
| 1 | 1,000,000 | 10,000 | accept | reject: claim mismatch; computed 100 |
| 0 | 1,000,000 | 0 | reject: below target | reject: below target |
| 79 | 10,000 | 7,900 | reject: below target | reject: below target |
| 80 | 10,000 | 8,000 | accept | accept |

MEASURED: the five tested control decisions are unchanged, for SIMULATED counts
of 85, 80 (at threshold), 79, 10, and 0 correct out of 100. This statement is
limited to those controls; it does not claim general behavioral equivalence.

The patched copy also rejects the SIMULATED low-score case with its corrected
canonical claim of 100 at either tested payload scale (10,000 or 1,000,000).
MEASURED: it reaches the below-target rejection, so fixing the claim alone
does not restore acceptance. The tests also check provider/hash rejections,
missing or malformed scale errors, and unchanged payloads. Endpoint trust
remains unresolved: the HTTP lookup test produces the same accept/reject
decisions for the proposed copy as for the original verifier.

MEASURED full-suite validation at the implementation commit above:
`60 passed, 1 skipped in 1.78s`. The skip is the untracked local
`legacy/retired_llm_phase/tests/test_geometry.py` because `sklearn` is absent.
Command from the repository root:

```powershell
$env:PYTHONPATH='hadagent/src'
.venv\Scripts\python -m pytest -v -rs 2>&1 | Tee-Object -FilePath 'test_results/astra-p002/full-suite-3886e24.txt'
```

OpenCode's clean-checkout rerun at the same implementation commit is CONFIRMED:
MEASURED `23 passed in 0.88s` for the targeted files and `60 passed in 4.00s`
for the full suite, with no skip. Outputs are
`.agents/work/opencode/p002_3886e24_targeted.txt` and
`.agents/work/opencode/p002_3886e24_full_suite.txt`. From the clean worktree,
OpenCode used the existing environment with these commands:

```powershell
$env:PYTHONPATH='hadagent/src'
& 'C:\Users\matth\OneDrive\Desktop\RedTeamHarness\.venv\Scripts\python.exe' -m pytest tests/test_podl_score_scale.py tests/test_podl_endpoint_trust.py tests/test_podl_fixed_scale.py -v
& 'C:\Users\matth\OneDrive\Desktop\RedTeamHarness\.venv\Scripts\python.exe' -m pytest -q -rs
```

The named output is local and ignored by Git. These are unit-level observations
with SIMULATED evaluation data; no model accuracy, signed record, block,
running chain, or GPU nondeterminism was tested. A supporting read-only code
review found no remaining blockers; it does not replace opencode or reviewer.
No merge into `main`, push, or external sharing was performed.

## 2026-10-08: P-005 offline experiment preparation

Implemented `experiments/honest_agreement/` and its stub tests at
`62c4ca24edac0e636523ff69331189f40296cbd9` on `astra/real-verifier`.
This is GREEN preparation: no downloads, sockets, real model execution, or
llama.cpp binaries were used in its tests. The runner calls HadAgent's real
`score_exact_match` with its fixed `DecodeConfig` and hashes the same completions
the scorer grades. The matrix mode represents the paper-described validator
reexecution design. A separate mode pairs idle and concurrent-load scoring on
one server instance, matching the prototype's miner-endpoint re-query path.

The runner checks local artifact and source identities, limits transport to its
owned loopback endpoint without proxies or redirects, records failures, and
cleans up its server on errors and interrupts. It enforces the reference-score
gate and execution deadlines. The analyzer requires the original plan, separates
output agreement from score agreement, excludes the reference from comparison
denominators, and reports failed or missing runs. Same-instance load comparisons
are reported separately. These are descriptive score-equality components, not
full-verifier or chain acceptance, deployment false-positive rates, or a
contradiction of the paper's differently scoped tampering-detection result.

MEASURED harness validation at the implementation commit: **98 passed, 1 skipped
in 5.31s**, exit code 0. All model-like inputs and experiment rows in the added
tests are SIMULATED. The skip remains the untracked legacy test that requires
`sklearn`; it is absent from a clean checkout. The inherited validation-metrics
summary printed by the suite concerns synthetic fixtures, not real-model
agreement. Command from the repository root:

```powershell
$env:PYTHONPATH='hadagent/src'
.venv\Scripts\python -m pytest -q -rs 2>&1 | Tee-Object -FilePath 'test_results/astra-p005/full-suite-62c4ca2.txt'
```

Output SHA-256:
`F90A673C72D1301CADFCBA6809A602131C9B0C0D45E010DAE4BEF2B08665A890`.
Plan-only validation at the same commit succeeded and printed the predeclared
run IDs; these are design choices, not completed runs:

```powershell
$env:PYTHONPATH='hadagent/src'
.venv\Scripts\python -m experiments.honest_agreement.run --config experiments/honest_agreement/plan.example.json 2>&1 | Tee-Object -FilePath 'test_results/astra-p005/plan-only-62c4ca2.txt'
```

Output SHA-256:
`7E38BC2907E5C387C000F6F2B323D5EBCCABC1607E2E2C39BC6679FB6813FDDF`.
Both outputs stay local and ignored. `hadagent/src`, `core`, and the dependency
list are unchanged from the prior implementation. No merge or push occurred.

The README is an **unresolved candidate manifest**, not a verified download
list: exact llama.cpp release tags/assets, immutable model/data revisions,
publisher digests, dataset download location, and licenses still need authorized
source verification. It marks these gaps explicitly rather than inventing pins.
The final outbox check found Matthew's recorded P-005 approval dated
2026-10-08 16:38. This task stayed within the user's explicit offline preparation
and no-download scope. Reference calibration, downloads, real inference, and CLI/backend compatibility checks have
not happened. OpenCode's independent rerun and reviewer's wording approval are
also pending; no empirical model-agreement result is ready for the paper or CRA.

## 2026-10-08: P-005 first real calibration stopped at the frozen limit

Matthew's P-005 approval was confirmed out of band by Claude at 18:05. The
original offline harness at 62c4ca2 had already been CONFIRMED by OpenCode
(17:13), and reviewer approved its scoped preparation claim (17:40). Before
real execution, b3ede3bbca285f6053b0efab8b07a8fec723f102 applied reviewer's
reporting flags: HadAgent-rule prefix scores rather than MMLU accuracy,
matched non-bare-letter diagnostics, and explicit failed/missing/backend
coverage and comparison denominators. These additions await a separate
OpenCode rerun.

The deterministic CSV builder is in dfbdf2e01058318409c8cde727d4daf81da633f6.
Its first full-suite run encountered a collection error in the downloaded
MMLU source's own test_calibration.py (missing pandas), preserved in
`test_results/astra-p005/full-suite-eval-preparation.txt`. Commit
c159898da841419920e6c5cb61500ab19f5f4f09 excludes the ignored download
folders from project-test discovery; no dependency was installed. MEASURED
at that commit: **104 passed, 1 inherited legacy skip in 4.42s**, exit 0:

```powershell
$env:PYTHONPATH='hadagent/src'
.venv\Scripts\python -m pytest -q -rs 2>&1 | Tee-Object -FilePath 'test_results/astra-p005/full-suite-artifact-isolation.txt'
```

Output SHA-256:
`E0D7A7D9BE29F425F8C79BC477102C9B0726E77BB8A59D810B8C27DA9718FB2D`.
The new tests use SIMULATED model-like inputs; the inherited validation-metrics
summary is not a model-agreement result.

Official artifact URLs, publisher digests where available, licenses, local
hashes, hardware, and the frozen plan are documented in
`experiments/honest_agreement/MANIFEST_2026-10-08.md` at
74a87ea2263b38c7eb4c42fe358477649fad0a31. The selected model is the pinned
Qwen2.5-1.5B-Instruct Q4_K_M GGUF. Build A is llama.cpp b11514 (CPU/Vulkan),
and B is b11513 (CPU). Archive and model publisher checks passed before use;
MMLU has no published cryptographic digest in the checked sources, so its
saved SHA-256 is explicitly local evidence. Qwen's license is Apache-2.0;
llama.cpp and MMLU are MIT. The dataset's license is supported by its pinned
official CAIS card, not inferred solely from its code repository.

The fixed eval set was built without changing the predeclared selection or
prompt template:

```powershell
.venv\Scripts\python -m experiments.honest_agreement.prepare_evalset --test-directory experiments/honest_agreement/local/sources/mmlu/official-data/data/test --plan experiments/honest_agreement/plan.example.json --output experiments/honest_agreement/local/evalsets/mmlu-fixed-100.jsonl --manifest experiments/honest_agreement/local/evalsets/mmlu-fixed-100.selection.json
```

Command output is saved in `test_results/astra-p005/eval-preparation-c159898.txt`.
Eval JSONL SHA-256:
`337118581a78bc8b083030e5c5642480f3d4401d69dc486728dddc83f3049a51`.
The frozen calibration plan's canonical hash is
`e6efe29d177017e018385a3e9df2c9d2fe0a563028e288dd21a69ec5f643fa21`.

MEASURED real calibration at **74a87ea2263b38c7eb4c42fe358477649fad0a31**:

```powershell
$env:PYTHONPATH='hadagent/src'
.venv\Scripts\python -m experiments.honest_agreement.run --config experiments/honest_agreement/local/plan.calibration.json --output experiments/honest_agreement/local/results/calibration.jsonl --execute --calibrate --approval-note 'P-005: matthew.md 16:38; claude.md out-of-band confirmation 2026-10-08 18:05' 2>&1 | Tee-Object -FilePath 'test_results/astra-p005/calibration-74a87ea.txt'
```

The predeclared one-thread CPU reference **failed** at our harness's fixed
600-second session limit, which we had set without a throughput measurement.
It reported `TimeoutError` in scoring after **50 of 100 completed items**, at
**600.031 seconds** for the
session. The command exited 1; the owned server process was confirmed gone.
There is no finalized HadAgent-rule score, matched non-bare-letter count, or
agreement statistic. Per-item outputs were not recorded, so no partial score
exists or can be computed from the retained evidence. This was our planning
error, not a demonstrated model or HadAgent failure. The timing/count evidence
is MEASURED and was independently CONFIRMED by OpenCode on 2026-10-08;
OpenCode's review also confirmed the frozen hashes and absence of any score.
The reference was not retried, the timeout was not extended, and neither the
planned matrix nor the separate idle/load condition was started. Vulkan
inference was unattempted; it is not being labeled a failed Vulkan cell.

Primary evidence (local, ignored):

- `experiments/honest_agreement/local/results/calibration.jsonl`, SHA-256
  `cc0c4a3ed32d8a7e04db7a68680c44c6469c527e5732830ba1c8cfed0d869da5`.
- Its server log under `calibration-logs/`, SHA-256
  `b3c0f7d826d06d92bf34c6498d80c559caca666b4ccee71f7ea42c5bcf90c99d`.
- `local/results/calibration.failure-summary.json`, a summary of that failed
  row with score/agreement fields explicitly null.
- `local/results/post-calibration-integrity.json`: every pinned model, eval-set,
  executable, runtime file, and source identity passed an explicit post-failure
  check. The runner's automatic post-check is on the success path, so this
  verification was done separately after the failed attempt.

The analyzer was also invoked with the frozen calibration plan and rejected
this failed reference as designed (exit 1, no replacement). Its error is saved
in `test_results/astra-p005/calibration-analysis-74a87ea.txt`. A network snapshot
showed the owned server listening and communicating on loopback only; the
loaded module snapshot identified the CPU Haswell backend. These are snapshots,
not continuous network tracing. Both are saved under `local/sources/`.

This outcome establishes that the chosen reference did not finish under the
frozen session limit on this machine during this attempt. It supplies **no
honest-node agreement or false-positive estimate**, and makes no comparison to
the paper's tampering-detection result. A longer run would require a distinct,
explicitly reviewed plan revision; the failed pilot remains part of the record.
No `hadagent/src` edit, system change, merge, or push occurred.

## 2026-10-08: P-005b proposal and offline P-008 desktop preparation

Posted P-005b as an AMBER timing-only amendment. Its SIMULATED/planned design
uses an 1,800-second session limit, six fixed cells with one repeat each, a
separate idle/load calibration and pair, and one persistent six-hour budget
that charges the failed pilot once. The reference, model/eval/template,
DecodeConfig and score gate remain fixed. No new model evaluation occurred.
The full reasoning, fixed cuts, caps and cross-machine comparison are in
`experiments/honest_agreement/P005b_PROPOSAL.md`; execution awaits consensus
and OpenCode's controller check.

Prepared a private desktop review bundle with the existing model/eval data,
relocated historical plan, proposed desktop/laptop plans, original prototype
source, portable harness, vendored dependency inventory, artifact pins,
strict manifest verifier, guarded preparation tools and PowerShell runbook.
The desktop adds a separately analyzed FP16 GGUF condition, not BF16. It pins
one RTX 3060 device per GPU build and makes no data-center generalization.

All preparation is GREEN and local. The official embeddable Python archive and
publisher digest are absent locally, so that pin stays explicitly unresolved;
no installer or guessed checksum is substituted. The remaining desktop
artifacts are pinned from saved official metadata and downloaded only after
P-008 approval. No network, transfer, inference or dependency installation was
performed during this work. P-008 also waits for the exact desktop specs,
P-005b decision, independent bundle review, and Matthew's recorded out-of-band
confirmation. Local private paths/logs are excluded from return copies.

The harness now checks artifact/source integrity on failure as well as success.
Synthetic tests cover the persistent deadline across processes, consumed
failed stages, final-write overruns, the fixed missing-cell order, device
selection, archive safety, manifest tampering and returned plan binding. These
are software checks, not model-agreement evidence. Exact test output, commit,
bundle manifest hash and ZIP hash are recorded in Astra's coordination outbox.

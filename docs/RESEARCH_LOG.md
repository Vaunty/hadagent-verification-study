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
honest-model behavior. OpenCode posted CONFIRMED on 2026-10-08 at 14:22;
reviewer approved the claim's wording the same day at 14:30, with the source
reference and skip clarification now recorded here. P-002 has cleared for the
endpoint test and proposed fix, subject to the recorded conditions. Astra has
not pushed or shared the branch. External use remains blocked by P-003.

## 2026-10-08: endpoint test and proposed scale fix (P-002, internal only)

P-002 cleared with reviewer's conditions. The implementation is on
`astra/real-verifier`, commit `3886e2489fd7ebf6f7bf4b8ab30f43fbcd2efb29`.
HadAgent's source and block-validation path remain unchanged. The observations
below await opencode's clean-checkout confirmation and reviewer's wording
review before use as project or paper evidence.

`tests/test_podl_endpoint_trust.py` constructs a lookup table from a synthetic
eval set inside the test and replaces only `urllib.request.urlopen`. The real
file loader, parser, request builder, scorer, and original verifier execute.
SIMULATED inputs: 5 prompt/answer pairs, payload scale 10,000, threshold 8,000,
and matching claims of 10,000 for table answers or 0 for deliberately wrong
answers. MEASURED decisions: the original verifier accepts the table answers
and rejects the wrong-answer control. Each run checks the requested URL,
request body, and complete prompt sequence. No network request, server process,
real benchmark answer key, or model is involved.

`core/podl_verifier.py` contains a proposed patched copy with a fixed protocol
scale of 10,000. It interprets claims in those same units and requires
`correct * PROTOCOL_SCORE_SCALE >= threshold * total`. It still parses the
payload's scale to preserve input errors, but that value cannot change the
arithmetic. This is a proposal for the authors; it is not an upstream fix.
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

The named output is local and ignored by Git. These are unit-level observations
with SIMULATED evaluation data; no model accuracy, signed record, block,
running chain, or GPU nondeterminism was tested. A supporting read-only code
review found no remaining blockers; it does not replace opencode or reviewer.
No merge into `main`, push, or external sharing was performed.

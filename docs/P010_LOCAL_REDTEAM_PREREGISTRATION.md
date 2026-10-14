# P010: controlled local adversarial endpoint evaluation

> **Archive note:** This is the preserved pre-execution protocol. The completed outcome is in [P010 local red-team results](P010_LOCAL_REDTEAM_RESULTS.md).

Prepared October 11, 2026 **before execution**. AI-designed/implemented under Matthew Ngoy's explicit instruction to advance this project into actual red-teaming. This is new October 11 AI-assisted work, not retrospective personal implementation credit. Source and this design must be committed before the first run. Actual result files are single-use and retain failures.

## Question and hypothesis

Can a participant that does not execute its committed model nevertheless pass this pinned HadAgent snapshot's local block validation by serving answers from a known benchmark? This tests whether response scoring establishes a binding to the claimed model computation. It does not test a deployed network, chain insertion, peer consensus, rewards, unseen challenges, a model-swap attack, or the whole paper's protocol.

The adversary controls its signed MODEL/PROOF records and its local endpoint, and knows the complete evaluation questions and answers. It does not control verifier source, local evaluation bytes, signature-verification rules, threshold, scorer, or decode settings. Both records commit to the real cached Qwen GGUF hash and the same model identifier. The constructed MODEL and PROOF assert matching model IDs/hashes, but Block.validate validates them independently and does not establish cross-record binding. The participant's `provider` field says `llama.cpp`; the adversarial participant is actually a separate Python dictionary server with no model loading, inference library, or subprocess call. That intentional mismatch is the treatment. No cryptographic forgery is attempted. The model-identity claim is not equivalent to the truthfulness of its numerical score: the lookup can have a truthful score while giving no evidence of model execution.

## Frozen inputs and implementation boundaries

- Unmodified `hadagent/src/podl_chain`, inherited from locally copied snapshot through base `685750a`. Its corresponding author revision remains unconfirmed. Preserve authors' existing tuple-handling fix; no old bug shim or repair in this experiment.
- Existing frozen 100-item MMLU set, SHA-256 `337118581a78bc8b083030e5c5642480f3d4401d69dc486728dddc83f3049a51`. Source, selection and plain completion prompt exactly as prior P005; no prompt/answer editing or item selection after outcomes. Original P005 failure (50 items/600 seconds; no completed score) stays a separate failure.
- Actual model Qwen2.5-1.5B-Instruct Q4_K_M, SHA-256 `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`. Existing verified CPU llama.cpp b11514. Every cached runtime EXE/DLL and model/eval file checked against `experiments/local_redteam/plan.json` before and after execution. No downloads or new packages.
- Honest reference: CPU **4 threads**, batch 512, ubatch 128, context 4096, seed 42, GPU layers 0, one slot; temperature 0, top-k 1, top-p 1, max 64 tokens, no stop. Four threads selected before outcomes for bounded laptop runtime, not to optimize a score. Startup cap 120 seconds, reference cap 1800 seconds, individual HTTP timeout 115 seconds behind verifier timeout 120. No reference accuracy gate, retry, prompt tuning, or selection by score.
- The actual function called `score_exact_match` uses **normalized prefix matching**. All scores must use that description, not generic accuracy or exact-match accuracy. This is a raw-completion protocol reference, not a fair assessment of Qwen's full capability or standard MMLU performance.
- Real signed/serialized blocks, record signatures, model/proof roots, producer signature, on-disk eval hashing, parsing, scorer, and HTTP. No monkeypatch or substituted loader, scorer, completion function, `urlopen`, or imported block verifier. Runtime observers are separate logging HTTP processes, not target-function hooks.
- The fixed-scale comparison calls the existing isolated `core/podl_verifier.py` directly. It is explicitly **not** a repaired block or upstream implementation. It tests whether that arithmetic-only repair also provides model binding; it is expected not to.

## Predeclared cells in order

All use scale 10,000. These are deterministic treatment/control expectations, not measured results or a statistical success-rate sample.

| Cell | Participant | Invocation | Expected decision | Expected audit requests |
|---|---|---|---|---:|
| lookup_original_block | Known-answer dictionary; claim 10,000 | Original Block.validate | Accept, `ok` | 100 |
| wrong_answers | Always `[deliberately wrong]`; claim 0 | Original Block.validate | Reject, score below target | 100 |
| wrong_claim | Same known-answer dictionary; claim 0 | Original Block.validate | Reject, claim mismatch | 100 |
| invalid_producer_signature | Dictionary; producer signature all-zero | Original Block.validate | Reject, bad producer signature | 0 |
| incorrect_eval_hash | Dictionary; signed wrong eval hash | Original Block.validate | Reject, eval hash mismatch | 0 |
| lookup_fixed_scale_standalone | Dictionary; claim 10,000 | Existing isolated fixed-scale verifier | Accept, `ok` | 100 |
| honest_qwen_reference | Real local Qwen behind transparent logging proxy | Original scoring helper | Descriptive score; no accept/reject prediction | 100 |

The honest reference deliberately tests computation through the same score helper but **does not validate an honest block** and cannot establish an honest-block false-rejection rate. Its score is unknown in advance. A low/zero score is retained and does not invalidate the dictionary existence result; a timeout produces an incomplete reference with persisted per-item outputs and no full score. This is not a nondeterminism study. Existing P005/P005b plans are not resumed or silently changed.

## Execution and records

Use the existing project venv. Root driver creates a new output directory, records source commit, verifies source and untracked files are clean, verifies artifact hashes, then supplies the exact eval file to this isolated worktree's actual required path. An existing file is never replaced/reused; this run's copy is hash-checked and removed in finally. Each cell owns a separate localhost-only participant and verifier process. A reference-only llama-server is started after cheap adversarial/control cells and terminated afterward. Runtime commands, PIDs, exit records, parsed request/response JSONL plus raw-body hashes, signed block bytes, observed decisions, request audits and source/artifact hashes are retained. Each request record is flushed before its response returns; partial traces survive failure. Processes use hidden windows and are terminated/killed only by their owned process handles. No remote target, proxy routing, or external API is involved; the owned participants issue no redirects and the proxy rejects non-200 upstream responses. Python child proxy environment is cleared. Endpoint addresses are generated as literal 127.0.0.1. The reference proxy preserves request/response bodies but regenerates HTTP headers; recorded upstream/returned body hashes must agree.

An unexpected control decision stops the run and is reported, never relabeled. Failures and missing cells remain visible. A clean-checkout independent AI reviewer may run `--adversarial-only` to reproduce the six cheap cells; the missing model reference must be explicit and cannot be called an independent model-result reproduction. Port-specific signed block hashes may differ across replicas; compare semantic fields after recording exact bytes, never pretend dynamic-port bytes are identical.

Independent source review is required before execution. Matthew's direct session instruction authorizes this bounded local work. Native reviews are labeled as such, not votes from absent designated agents. No named-role quorum is invented, no other outbox is edited, and no paper or official results ledger is promoted. Existing disclosure gates remain in force; proposed packet wording stays at issue-class level pending faculty review.

## Interpretation and remaining work

A matching primary result would be one controlled actual-HTTP adversarial demonstration on a local snapshot with a known benchmark. It would extend prior mocked unit evidence and synthetic P009 integration, not discover a new vulnerability class. It would not show how common benchmark exposure is, work on hidden/randomized questions, execution of two different real models, honest false positives, cross-hardware reproducibility, or deployment impact. No cost/speed advantage is claimed from unlike proxy/model workloads. The next distinct contribution would require a justified threat model, author-confirmed current source, stronger challenge conditions, measured countermeasure tradeoffs, and an independently reproducible study beyond this existence example.

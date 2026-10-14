# Scope and claim map

This note connects the repository's findings to the exact copied code and to the HadAgent paper's stated design. It is meant to prevent three different questions from being collapsed into one:

1. Does the copied validator make the decision its code describes?
2. Does that copied implementation enforce the paper's intended verifier design?
3. Does matching an output prove that the prover performed fresh physical computation?

The experiments answer parts of the first question and identify gaps relevant to the second. They do not solve the third.

## Copied snapshot behavior

The repository does not record the exact upstream commit from which `hadagent/src/podl_chain/` was copied. The observations below therefore apply to this snapshot, not automatically to current upstream code.

| Boundary | Exact copied source | What it enforces | What it does not enforce |
|---|---|---|---|
| MODEL record | `records.py`, `make_model_commit` lines 105-122 and `_validate_model_commit` lines 205-244 | Required metadata shape and an owner signature over model ID, artifact hash, storage reference, and timestamp | Artifact retrieval or proof that the artifact ran |
| PROOF record | `records.py`, `make_podl_llm_eval` lines 125-156 and `_validate_podl_llm_eval` lines 247-314 | Required metadata shape and a miner signature over endpoint, model/artifact claims, score fields, and timestamp | Cross-record consistency with a MODEL record; `score_scale` range or canonical value |
| Block validation | `block.py`, `Block.validate` lines 90-133 | Height and prior hash passed by the caller, record validation, lane roots, producer signature, and a PoDL check with fixed threshold `8000` | A pairing rule between MODEL and PROOF records; a model loader; network consensus |
| PoDL evaluator | `pdl.py`, `score_exact_match` lines 71-77 and `verify_podl_llm_eval` lines 81-122 | Provider string, local eval-set hash, fixed decode hash, endpoint responses, score-claim equality, and threshold | Independent model execution; use of `base_model_id`, `artifact_hash`, or `artifact_ref`; exact equality despite the helper name |
| Local ledger | `ledger.py`, `Ledger.append` lines 36-46 | Calls block validation against the file-backed tip, then writes the block | Fork choice, distributed agreement, rewards, or peer propagation |
| Loopback hub | `hub.py`, `handle_packet` lines 54-145 and record handlers lines 193-298 | Accepts and signs MODEL/PROOF submissions and serves pool sync | A `BLOCK_ANNOUNCE` handler or peer-to-ledger path, although the enum declares that packet in `packets.py` line 16 |

The score helper performs normalized prefix matching: it accepts an output whose normalized text starts with the normalized answer. Its name, `score_exact_match`, is therefore misleading. Result documents report scores under this repository-specific rule and do not label them standard benchmark accuracy.

## Score-scale defect

`records.py` checks only that `score_scale` is an integer. `pdl.py` then computes

```text
computed_scaled = floor(correct * score_scale / total)
```

and `block.py` supplies the fixed threshold `8000`. Because the proof chooses the units while the threshold remains fixed, changing `score_scale` can change eligibility without changing the fraction correct. This is an arithmetic and validation defect in the copied implementation.

P012 measures this path over a finite, preregistered synthetic grid. The original accepted 70 of 78 constructed cases whose underlying correctness was below 80%; an isolated repair using fixed 10,000-point units accepted none. Both arms accepted all 6 eligible canonical controls. The finding is exact for that finite cohort. It is not an estimate of adversary prevalence, deployed impact, or current upstream behavior.

## Model identity and execution

The signed records contain model and artifact fields, but `verify_podl_llm_eval` does not read them. It sends the local evaluation prompts to the endpoint supplied in the proof. P010 shows that a constructed participant with known benchmark answers can satisfy both the original score path and the isolated arithmetic repair without loading the named model.

The [HadAgent paper](https://arxiv.org/html/2604.18614v1#S3) describes a stronger intended system. Section III-A fixes the weights, input, and deterministic decoding for a forward pass. Section III-B binds a model record to an artifact through a model hash. Section III-D says master nodes independently recompute sampled recent tasks and use majority voting. The endpoint-query behavior in this snapshot does not implement that independent-master check. The supported claim is therefore an **implementation-to-design gap in the copied prototype**, not a protocol-wide model-identity break.

A model hash alone binds an identifier or record to an artifact; it does not prove that a particular output came from executing that artifact. Independent recomputation can check output equivalence under the fixed computation. Even perfect output agreement cannot, by itself, prove that the prover freshly performed the work: a cache of known prompt-output pairs can return the same valid output. Establishing physical work or freshness needs an additional mechanism and threat model.

## Honest baseline

P013 used the named local model and pinned runtime in two fresh server processes. Its claim and validation phases produced identical generated text on all 100 prompts and the copied scorer returned 28/100 in both phases, or 2800/10000. The validator correctly rejected the truthful claim below the 8000 eligibility threshold.

This establishes local output and score reproduction for one fixed configuration. It does not estimate false rejection because there were zero eligible honest acceptance trials. It also does not exercise the paper's independent master-node implementation or prove fresh prover-side execution.

## Ledger and network limits

The local ledger measures a useful but narrow boundary: it prevents an exact old block from being appended at the wrong height and requires the expected prior hash. A valid proof record could still be placed in a newly signed, correctly linked block in the constructed test. The source does not state a one-to-one MODEL-to-PROOF pairing rule, so acceptance of inconsistent signed metadata is reported as missing cross-record enforcement rather than automatically called a protocol violation.

The loopback hub transports records and supports pool synchronization. It returns an unhandled-packet error for `BLOCK_ANNOUNCE`. No experiment in this repository establishes peer block propagation, distributed consensus, fork choice, reward effects, Sybil economics, or deployed-chain impact.

## Contribution boundary

The defensible contributions in this repository are:

- a reproducible implementation-level counterexample for the score-unit defect and an isolated arithmetic repair;
- a finite grid showing that the repair removes those constructed acceptances without rejecting the eligible synthetic controls in that cohort;
- controlled studies separating signed metadata, endpoint score validity, named-model execution, ledger append, and peer transport;
- a real-model local baseline with explicit denominator and scorer limits; and
- evidence-preserving runners and result records that distinguish synthetic fixtures, measured decisions, and AI review.

The work does not establish novelty relative to all prior research, current upstream susceptibility, exploitation of a deployed system, economic impact, or defeat of the full paper design. Those require separate literature review, version correspondence, and system-level evidence.

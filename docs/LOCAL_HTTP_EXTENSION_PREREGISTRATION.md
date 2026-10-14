# P010 local HTTP extension preregistration

Status: frozen before first execution. This protocol is a session-specific local extension requested by Matthew on 2026-10-11. The design and implementation are AI-assisted; no designated OpenCode or reviewer vote is claimed.

## Question and boundary

This experiment asks what the committed HadAgent `Block.validate` implementation accepts when independently signed MODEL and PROOF records disagree, a signed proof is reused, an owned HTTP participant changes its answers, or the local challenge bytes change. It runs the unmodified verifier at commit `32f407b55c7a44b06de2afa9822b4200bb25209b` against an owned `127.0.0.1` server and the frozen 100-item P010 evalset.

The evidence boundary is `Block.validate`. This is not a ledger, peer, consensus, or public-chain test. The HTTP answers are synthetic lookups or constants; no model is loaded and the earlier Qwen reference is not rerun. Acceptance therefore means only that this local validation path returned `True`. Replay cells do not establish that a full network would accept replay. The known benchmark and deterministic public test key also rule out claims about unseen challenges, key theft, or a real miner.

## Frozen cases and oracles

Every case uses real record signatures, lane-root recomputation, producer signing, evalset hashing, the committed prefix-match scorer, and actual loopback HTTP requests. A result counts as measured only if `Block.validate` returns normally and the exact decision, reason, request count, and response-category counts are recorded.

| Case | Treatment | Frozen oracle |
|---|---|---|
| `baseline` | Matching signed MODEL and PROOF; lookup returns every frozen answer | accept `ok`; 100 lookup responses |
| `signed_artifact_mismatch` | Re-sign PROOF with an artifact hash different from MODEL | accept `ok`; 100 lookup responses |
| `signed_model_id_mismatch` | Re-sign PROOF with a base-model ID different from MODEL | accept `ok`; 100 lookup responses |
| `unsigned_proof_tamper` | Change signed PROOF payload without re-signing it | reject invalid PoDL signature; 0 HTTP requests |
| `repeat_identical_block` | Validate the exact baseline block bytes again | accept `ok`; 100 lookup responses |
| `reuse_proof_next_height` | Reuse the exact baseline PROOF record in a freshly signed height-2 block linked to the baseline hash | accept `ok`; 100 lookup responses |
| `same_signed_block_changed_responses` | Validate exact baseline block bytes after the same endpoint switches to constant wrong answers | reject claimed-score mismatch at computed 0; 100 wrong responses |
| `changed_challenge_stale_hash` | Replace local challenge bytes while retaining the baseline signed evalset hash | reject evalset-hash mismatch; 0 HTTP requests |
| `changed_challenge_signed_hash_stale_lookup` | Sign a new block to the changed challenge hash while the endpoint only knows the original prompts | reject claimed-score mismatch at computed 0; 100 unknown-prompt responses |

The two cross-record cases are evidence of missing MODEL-to-PROOF comparison only if the report independently confirms the mismatch and valid signatures. The two replay cases demonstrate stateless behavior only at the direct validation boundary. The changed-response case shows that acceptance depends on current endpoint output; it does not prove which model, if any, generated an output. Challenge cases show hash gating and stale-answer behavior for this constructed variant, not general challenge secrecy.

## Integrity and stopping rules

The runner refuses a dirty tracked worktree, a reused output directory, a pre-existing verifier eval fixture, a source evalset hash mismatch, an output path outside the private local-results folder, or module imports outside this worktree. It never patches the verifier. It records the frozen commit, script/plan/preregistration hashes, block and proof hashes, per-case request traces, source hashes before and after, and exact fixture cleanup. An oracle mismatch is preserved as a potential new finding rather than rewritten. An operational exception marks the run failed, while the partial report and original failed WinError 10013 attempt remain preserved separately.

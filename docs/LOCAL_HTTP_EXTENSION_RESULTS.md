# P010 local HTTP extension results

Status: primary run and native clean-worktree reproduction complete. All nine preregistered oracles matched in both runs. This document records local AI-run evidence, not a designated reviewer vote or a claim of independent human validation.

## Outcome

The frozen runner at commit `95beeda3853aca10b0f41c09a20bf6fd44498815` completed from `2026-10-11T09:26:56Z` to `09:26:58Z`. It exercised the committed `Block.validate` path over real loopback HTTP, real record and producer signatures, recomputed lane roots, and the original prefix-match scorer. Nine of nine cells completed without an execution error, all exact decision/reason/request-count oracles matched, and the request trace contained 700 responses in the preregistered order.

| Case | Measured decision | HTTP requests |
|---|---|---:|
| Matching baseline | accepted: `ok` | 100 |
| Signed PROOF artifact hash differs from signed MODEL | accepted: `ok` | 100 |
| Signed PROOF model ID differs from signed MODEL | accepted: `ok` | 100 |
| PROOF payload changed without re-signing | rejected: invalid PoDL signature | 0 |
| Exact baseline block validated again | accepted: `ok` | 100 |
| Exact baseline PROOF reused in a newly signed, linked height-2 block | accepted: `ok` | 100 |
| Exact baseline block with the same endpoint now returning wrong constants | rejected: claimed-score mismatch, computed 0 | 100 |
| Changed local challenge with stale signed hash | rejected: evalset-hash mismatch | 0 |
| Newly signed changed-challenge hash with lookup limited to old prompts | rejected: claimed-score mismatch, computed 0 | 100 |

The artifact and model-ID mismatches were independently confirmed in the serialized records, and all four records in those two cells validated individually. The repeated-block bytes were identical to baseline. The height-2 cell reused the identical PROOF-record bytes. The changed-response and stale-challenge cells reused the exact baseline block bytes. These relationship checks all passed.

## Interpretation and claim limits

The two accepted signed mismatches establish a narrower fact: this `Block.validate` implementation accepted a block containing one independently valid MODEL record and one independently valid PROOF record even though their model identifiers or artifact hashes disagreed. The source allows multiple records per lane and does not document a one-to-one MODEL-to-PROOF pairing rule. The result therefore shows absent cross-record consistency enforcement in this path; whether that is itself a protocol flaw depends on the intended pairing semantics. The broader model-binding concern still holds from P010: valid signatures and endpoint scoring did not establish which model artifact generated the HTTP output.

The repeat and height-2 cells show stateless acceptance at the direct validation boundary. The height-2 result is evidence that this method has no proof-freshness check tied to height or the prior block. The experiment did not call `Ledger.append`, run peers, or exercise consensus, so it must not be described as a measured network or full-chain replay.

The response-mutation control shows that identical signed block bytes can receive different decisions when the endpoint's current answers change. The challenge controls show that a stale challenge hash fails before HTTP and that this constructed prompt variant defeats the old lookup table after the new hash is signed. They do not establish challenge unpredictability, benchmark secrecy, or resistance to a participant that already knows future prompts.

No cell loaded or inferred with Qwen. The endpoint served frozen answers, constants, or an explicit unknown response. The benchmark was known locally, all keys were deterministic public test keys, and no external endpoint or chain was contacted. No oracle mismatch or unplanned finding occurred.

## Provenance and verification

- Target/source base: `32f407b55c7a44b06de2afa9822b4200bb25209b`.
- Frozen protocol and implementation: `95beeda3853aca10b0f41c09a20bf6fd44498815`.
- Runner blob: `d000ad7f35e77868bd2e2560f2d57e3188bb0064`; Windows file SHA-256 `caf2cd65b95bcc489294c826ae8d02c063c1adef2f216db81ed2d0d2ec1965a4`.
- Preregistration blob: `11352e68817e931921706279b3d85ef7cd396a28`; file SHA-256 `848b76e556526b5b7846095afb8f5d9ed556b0a52c9c25410de442489ea9b3c4`.
- Frozen evalset SHA-256: `337118581a78bc8b083030e5c5642480f3d4401d69dc486728dddc83f3049a51`; changed-challenge SHA-256: `6bd9aaf9c69679c3bb14525870047f4fb0f72f3a6ef30305f47d9a0e7557986d`.
- Primary report SHA-256: `d138ea61bdeaa93315dafa5c48529a457379636ebe13db0cf17d8a91f39e81d1`; request log SHA-256: `8b700d1927c6c41b38da1163c73333aab3a6f14f98f04dc8a64db9dd8c597a97`.
- Raw-artifact manifest SHA-256: `2ac2a0eec178064b659238982e85371b20f42aba74eb3c33c92c6f60bf455451`.
- A separate read-only artifact reconciliation passed with no discrepancies; audit log SHA-256 `f10df02a56dfe372b2621957e5c8464fe480508e5cfacddd69de28ac9edeb144`.
- Full existing suite: `184 passed in 13.60s`; log SHA-256 `7ff232c7eb588d288d099d6755871ef8952d951b79179cf89bf95a174c8afcad`.
- The owned verifier eval fixture ended with the expected changed-challenge hash and was deleted. Tracked source hashes matched before and after, and the worktree remained clean.
- A separate native AI agent reproduced the run from a clean detached worktree at the same frozen commit: 9/9 oracles, 700 requests, stable sources, and fixture removal. Replica report SHA-256: `01e13b1a76513d0cfc0ffe63fbf4f008d75c4466501c7430c196bd9b223cf729`.
- Root independently decoded both runs' blocks, checked signatures, lane roots, the actual field mismatches and proof reuse, reconciled all traces, and compared both reports. The audit JSON SHA-256 is `e55e0da9254a3c15dfb98625918cbb6b9d21d280fe5d69c47605f95c4f048a8c`.
- Both checkouts use runner blob `d000ad7f35e77868bd2e2560f2d57e3188bb0064`. Their raw runner-file SHA-256 values differ because one checkout uses CRLF and the other LF; this is checkout normalization, not a source difference.

The earlier separate-session draft attempt remains preserved with report SHA-256 `18aae2adf593921af0f6e15aa057c93c5910782b43ff20dc2f961d9b9b2e879f`; it failed before producing any row because its environment denied the first HTTP connection (`WinError 10013`). It is not counted as experimental evidence.

The original case proposal and failed draft came from a separate Astra/Codex session. A native Codex AI agent then audited the target source, corrected and preregistered the design, implemented the evidence controls, executed the primary run, reconciled the raw artifacts, and wrote this interpretation under Matthew's explicit direction. A separate root Astra AI run and audit supplied the clean-worktree reproduction. Matthew's role here was authorization and research direction; this record does not attribute the AI implementation or validation work to him. These native checks are not designated OpenCode/reviewer votes or human validation.

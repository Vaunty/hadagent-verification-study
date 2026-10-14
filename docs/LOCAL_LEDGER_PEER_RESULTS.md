# Local ledger and peer-boundary results

Status: the primary run and a separate clean-worktree reproduction are complete. All 13 preregistered oracles matched in both runs, with 500 HTTP requests per run. These are native AI-run checks under Matthew Ngoy's direction. They are not designated reviewer votes or independent human validation.

## Measured result

The frozen runner at commit `280e8d1dacaf2ec2100cd3def1c8295126c896ea` completed its first attempt from `2026-10-11T09:50:51Z` to `09:50:53Z`. It used the repository's unchanged `Ledger.append`, block validator, record and producer signatures, lane roots, file-backed ledger, newline-delimited TCP server/client, `InformationHub`, and `AIPool`. A local HTTP participant on `127.0.0.1` returned frozen answers to the known 100-item benchmark.

The ledger enforced height and prior-hash linkage. It rejected an exact replay of the already appended height-0 block before HTTP, and it rejected a height-2 block with the wrong prior hash. The same signed PROOF record was nevertheless accepted when placed in a newly signed, correctly linked height-1 block. This is a measured distinction between replaying the whole block and reusing a proof in a new block.

| Ledger cell | Measured decision | HTTP requests | State result |
|---|---|---:|---|
| Matching genesis block | accepted: `appended` | 100 | height -1 to 0 |
| Exact same height-0 block again | rejected: `height mismatch` | 0 | unchanged at 0 |
| Exact proof reused in linked height-1 block | accepted: `appended` | 100 | height 0 to 1 |
| Correct next height with wrong prior hash | rejected: `prev_hash mismatch` | 0 | unchanged at 1 |
| Signed MODEL/PROOF artifact-hash mismatch | accepted: `appended` | 100 | fresh ledger -1 to 0 |
| Signed MODEL/PROOF model-ID mismatch | accepted: `appended` | 100 | fresh ledger -1 to 0 |
| PROOF changed without re-signing | rejected: invalid PoDL signature | 0 | fresh ledger unchanged |
| Block built from records received over TCP | accepted: `appended` | 100 | fresh ledger -1 to 0 |

The `persisted_candidate` field is true for the rejected exact replay because the identical height-0 file was already present from the first append. State and file hashes before and after the replay are equal. The rejected call did not write or overwrite a block.

The actual loopback TCP checks produced the following responses:

| TCP cell | Measured response | Pool result |
|---|---|---|
| Valid MODEL metadata | `PONG`, `ok=true` | 0 to 1 |
| Individually valid but inconsistent PROOF metadata | `PONG`, `ok=true` | 1 to 2 |
| PROOF missing artifact hash | `ERROR`, `ok=false` | unchanged at 2 |
| Pool sync request | `POOL_SYNC_RESPONSE`, two items | unchanged at 2 |
| Serialized block announcement | `ERROR: Unhandled packet type: BLOCK_ANNOUNCE` | pool 0; separate ledger unchanged |

The two records returned by pool sync matched the records later removed through `build_records_for_block`. The runner constructed a signed block from them because the repository provides no peer block builder. A direct call to a separate local ledger then appended that block. Both records validated individually and disagreed on model ID and artifact hash.

## What this establishes

The height and prior-hash checks stop exact block replay and broken chain linkage at `Ledger.append`. They do not stop reuse of an old valid proof inside a newly signed, correctly linked block in this test.

The local ledger also accepted blocks containing one valid MODEL and one valid PROOF whose artifact hashes or model identifiers disagreed. The TCP hub accepted the same kind of inconsistent metadata as separate records, returned both through pool sync, and made them available to the direct pool-to-record method. The source permits multiple records per lane and does not state a one-to-one MODEL-to-PROOF pairing rule, so the measured fact is accepted inconsistent signed records. Whether that violates the intended protocol depends on semantics the repository does not specify.

The network boundary is narrower. Record submission and pool sync work over real loopback TCP. `BLOCK_ANNOUNCE` exists in the packet enum but has no handler, no peer-to-ledger wiring, and no consensus path. The error response is a useful negative result: this snapshot cannot support a claim that a peer propagated or accepted the block through the network.

## Evidence and checks

The primary report contains eight ledger rows and five TCP rows. Every row is marked measured and matches its frozen decision, request-count, pool-state, or ledger-state oracle. Its request log contains five ordered 100-request groups, for 500 total responses.

A read-only artifact audit decoded every candidate block and TCP packet, recomputed lane roots and producer signatures, validated the record signatures, checked exact proof reuse and block linkage, and compared accepted candidates with the persisted ledger bytes. It also confirmed that all rejected cells left their ledger state unchanged, the announced bytes matched the later direct-append candidate, source hashes remained stable, both servers stopped, and the owned evaluation fixture was removed.

A separate native Astra AI agent reproduced the frozen run in a clean detached worktree. That run also matched all 13 semantic oracles and made 500 requests. Its independent audit checked every candidate and persisted block, signatures, roots, packet bytes, pool-sync record identity, state transitions, cleanup, and source identity. Dynamic ports and hub timestamps change some raw block and packet hashes across runs, so agreement is semantic rather than byte-for-byte across worktrees.

- Target/source base inherited from the prior extension: `32f407b55c7a44b06de2afa9822b4200bb25209b`.
- Frozen implementation and preregistration: `280e8d1dacaf2ec2100cd3def1c8295126c896ea`.
- Runner git blob: `53b6f1344ccb8886a4e54cb7b61db3db0aa29d88`.
- Preregistration git blob: `ec538da33b037e56911e956532f9637d265f36f8`.
- Primary report SHA-256: `3a66b1232790b80741e32601a200cb812c2953739142fe4b3c688a1852e8fe17`.
- Primary HTTP trace SHA-256: `0204e2ecfe0cecf9755f7db540ebf7753403c00a35538bab6f786d81b79b4939`.
- Primary raw-artifact audit JSON SHA-256: `b4aa3518f5596bee7e5244a76d63b80b173fefb5a84da45ce2698cb4fc9a8c6b`.
- Replica report SHA-256: `f714d31de8228ec3306a619d43fe35ac09114aaaecbc52e08784063274768f5e`.
- Independent cross-run audit JSON SHA-256: `3f5b4baf3250dab71b269d2f484ad77279cbbd31654ae71dae4e631a47428df8`.

No target or unit-test code changed, so the existing 184-test suite was not repeated for this follow-up. The experiment ran only the new local runner against the previously tested source.

## Limits and attribution

The participant used known frozen answers. No model ran, no external endpoint or peer was contacted, and no hidden challenge, deployed chain, reward logic, current author revision, or field impact was tested. A local file-backed append is not consensus. Directly draining a pool and constructing a block is not peer block propagation.

A native Codex AI agent read the source, designed and preregistered the study, implemented the runner and evidence controls, executed the primary attempt, audited its artifacts, and wrote this result under Matthew's explicit direction. A separate root Astra AI agent performed the clean-worktree reproduction and cross-run audit. Matthew authorized and directed the work; this document does not attribute the AI implementation or validation to him.

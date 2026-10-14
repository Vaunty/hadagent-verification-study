# Local ledger and peer-boundary preregistration

> **Archive note:** This is the preserved pre-execution protocol. The completed primary run and clean-worktree reproduction are recorded in [Local ledger and peer-boundary results](LOCAL_LEDGER_PEER_RESULTS.md).

Status: frozen before first execution. Matthew explicitly requested this follow-up on October 11, 2026. A native Codex AI agent designed and implemented it under that direction. Native reviews and reproductions are supplementary AI checks, not designated OpenCode/reviewer votes or human validation.

## Question and implemented boundaries

The study asks which prior local extension results survive the next implemented state boundary, `Ledger.append`, and what the repository's peer transport actually accepts. It targets the unchanged copied source at base `32f407b` through the frozen extension history. It uses the real ledger, block validator, signatures, lane roots, file persistence, score routine, packet serialization, `AsyncNodeServer`, TCP client, `InformationHub`, and `AIPool`.

The peer implementation transports record-submission and pool-sync packets. Although `PacketType.BLOCK_ANNOUNCE` exists, `InformationHub.handle_packet` has no handler for it, and no peer-to-ledger wiring exists. The study therefore sends an actual block-announcement packet and expects an error. It does not call a direct handler a network test and does not invent a peer-consensus path. After peer-created records enter the pool over TCP, the runner explicitly calls the implemented pool-to-record method, constructs a signed block because no block builder is provided, and then calls a separate local ledger directly.

All sockets bind to owned `127.0.0.1` ports. The HTTP participant returns answers from the already frozen, known benchmark. No model, external endpoint, service, credential, download, peer network, consensus process, or reward logic is used. The target source is never patched or monkeypatched.

## Frozen ledger oracles

| Case | State and treatment | Exact oracle |
|---|---|---|
| `ledger_baseline_genesis` | Append matching height-0 block to empty ledger | append; 100 lookup requests; height -1 to 0 |
| `ledger_exact_block_replay` | Append exact same height-0 bytes again | reject `height mismatch`; 0 requests; ledger unchanged at 0 |
| `ledger_reuse_proof_next_height` | Reuse exact proof record in newly signed, correctly linked height-1 block | append; 100 requests; height 0 to 1 |
| `ledger_wrong_prev_at_expected_height` | Correct next height but wrong prior hash | reject `prev_hash mismatch`; 0 requests; ledger unchanged at 1 |
| `ledger_signed_artifact_mismatch` | Empty ledger; one valid MODEL and one valid PROOF disagree on artifact hash | append; 100 requests; height -1 to 0 |
| `ledger_signed_model_id_mismatch` | Empty ledger; one valid MODEL and one valid PROOF disagree on model ID | append; 100 requests; height -1 to 0 |
| `ledger_unsigned_proof_tamper` | Empty ledger; PROOF changes without re-signing | reject invalid PoDL signature; 0 requests; ledger stays empty |
| `peer_records_ledger_append` | Append block built from two valid, inconsistent records received through TCP and removed from pool | append; 100 requests; height -1 to 0 |

For every ledger case, the runner saves candidate bytes, state before and after, persisted block-file hashes, exact decision and reason, ordered HTTP trace, and whether rejection left state byte-for-byte unchanged. The direct replay oracle is expected to reject; hiding that rejection would invalidate the study.

## Frozen peer-transport oracles

| Case | Actual loopback TCP packet | Exact oracle |
|---|---|---|
| `tcp_model_submission` | Valid model metadata | `PONG`, `ok=true`; pool 0 to 1 |
| `tcp_mismatched_proof_submission` | Valid proof metadata whose model ID and artifact hash disagree with submitted model | `PONG`, `ok=true`; pool 1 to 2 |
| `tcp_malformed_proof` | Same proof metadata missing artifact hash | `ERROR`, `ok=false`; pool remains 2 |
| `tcp_pool_sync` | Pool sync request | `POOL_SYNC_RESPONSE` containing two items; pool remains 2 |
| `tcp_block_announce` | Serialized candidate block announcement after the pool is drained | `ERROR` with unhandled packet type; pool remains 0 and separate ledger stays empty |

The peer-created MODEL and PROOF must validate individually, actually disagree on both tested fields, be returned by the implemented pool-to-record method, and leave the pool empty before block construction. Acceptance of their block is a local transport/pool/ledger observation. The source permits multiple lane records and does not state a one-to-one MODEL-to-PROOF pairing rule, so this is not predeclared as a protocol flaw.

## Integrity and stopping rules

The runner refuses a dirty tracked worktree, reused output directory, pre-existing verifier fixture, wrong evalset hash, output outside the ignored local-results directory, or imports outside its worktree. It records the frozen commit and file hashes, packet bytes, HTTP trace, ledger directories and states, source hashes before and after, socket shutdown, and fixture removal. Oracle mismatches remain visible as potential new observations. Operational errors produce a failed partial report. The earlier extension runs and original failed draft remain untouched.

# P-006 record property validation

## Scope

This suite tests HadAgent's real `podl_chain.records.validate_record` function and the real `podl_chain.block.Block.validate` record-validation call site. It generates synthetic signed DATA, MODEL, and PROOF records with deterministic Hypothesis settings. It also builds signed blocks containing DATA and MODEL records only.

The block properties deliberately exclude PROOF records. `Block.validate` performs PoDL evaluation for those records, and this repository does not contain its expected eval-set file. P-006 is about record validation and the fixed tuple-handling call site; it does not test PoDL scoring, model execution, a network, or chain consensus.

## Properties

For each of the three record schemas, Hypothesis generates valid records from synthetic Ed25519 key seeds and schema-valid values. Every field covered by the record's signature is then changed one at a time without re-signing, while preserving the field's validated type and size. The suite also changes the 64-byte signature, removes every required field one at a time, and checks unsupported versions, lanes, and record-type numbers. All must be rejected by the real validator.

For non-PoDL blocks, the suite generates one to six valid DATA/MODEL records, computes the real lane roots, signs the real block header, serializes and deserializes the block, and checks acceptance. A second property mutates one record signature, then recomputes the roots and block signature around that invalid record. The real block validator must reject it specifically at record validation.

The regression test includes a small local shim for the historical truthy-tuple pattern: it asks `if not validate_record(record)` instead of unpacking the returned `(valid, reason)` tuple. The property shows that this local model accepts a generated invalid-signature record while the current real `Block.validate` rejects it. Project records attribute the fix to the HadAgent authors' commit `a4ec9da`. The historical source revision is not present here, so this is a regression model of the documented bug pattern, not a checkout or execution of the authors' old code.

## Boundaries

The suite does not claim that every arbitrary byte mutation must be rejected. It covers all authenticated payload fields with schema-preserving changes, signature changes, missing required fields, and unsupported record envelope metadata. Extra fields, unauthenticated extensions, malformed MessagePack, PoDL semantics, proof scoring, live models, network behavior, and peer or chain acceptance are outside this suite.

Hypothesis uses `max_examples=64`, `derandomize=True`, `database=None`, and a one-second per-example deadline. No health checks or deadlines are suppressed. Failures retain the minimized counterexample in pytest output; because the example database is disabled, an independent rerun should use the same test commit and command. If Hypothesis prints a `@reproduce_failure(...)` blob, preserve it verbatim with the log. An unexpected failure on unmodified HadAgent code is a candidate finding: stop, preserve the minimized case, and do not weaken or filter the property.

## Dependency and execution

`requirements-dev.txt` pins `hypothesis==6.168.0`, the version already installed in the shared project environment. P-006 did not install or upgrade anything.

The executor must run from the dedicated worktree with its own `hadagent/src` first on `PYTHONPATH` and the existing main-repository virtual environment. Raw logs belong under the ignored `test_results/astra-p006/` directory. Record the branch, base and result commit, commands, exit codes, Python/pytest/Hypothesis versions, and log hashes before requesting an independent clean-checkout rerun.

## Results

Run locally on 2026-10-11 from branch `astra/record-properties-20261011`, based on `31f16461302d22ff51f7c5e19282ff3a16ae16ed`. The source was still an uncommitted review diff, pinned by the test-file SHA-256 below. All generated keys, records, mutations, and blocks were **SIMULATED**. Pytest outcomes and decisions returned by the unmodified validators were **MEASURED**.

- Targeted command: `python -m pytest -q --hypothesis-show-statistics tests/test_records_properties.py`
  - **MEASURED:** 7 tests passed in 3.12 seconds; each property completed the configured 64 passing examples with zero failing examples.
  - Hypothesis reported 11, 9, and 10 internally discarded generation attempts for the three variable-length block properties. Each still completed all 64 valid examples, and no health check was suppressed.
- Full-suite command: `python -m pytest -q`
  - **MEASURED:** 178 tests passed in 10.73 seconds.
- **MEASURED environment:** Python 3.14.4, pytest 9.1.1, Hypothesis 6.168.0.
- Test source SHA-256: `A098A81A181AADB74730CD3754DCD0D846E419DDDC2E4CD3E789EDE50D000FE5`.
- Targeted log: `test_results/astra-p006/targeted_hypothesis.txt`; SHA-256 `B2E9AD3A252F88F1E4CB1528CCA79ACA4778AFC49F5E04D87E43C9E9B832A628`.
- Full-suite log: `test_results/astra-p006/full_suite.txt`; SHA-256 `26F3FFB177A51F239AFF25AA072B6EAE00F5A6C5E41CE2E1C0F82459DE0E3C57`.
- Existing full-suite metrics artifact copied to `test_results/astra-p006/full_suite_validation_metrics.json`; SHA-256 `B15594FAC3087768D02105789C967CF4014070F462A5B9ACD141D7C973544074`.

No unexpected failure appeared in the real record or block validator, so there is no candidate new finding from this run. Root subsequently reviewed the full test source and committed it as `279eeb0e2d50237a02d70298117db12c07ab23cb`. The following independent native-agent check supplements that review. The designated OpenCode rerun and reviewer wording approval remain pending before promotion into the findings ledger, paper, or application claims.

## Independent native-agent reproduction

A separate Codex agent reviewed and reran commit `279eeb0e2d50237a02d70298117db12c07ab23cb` in the clean detached worktree `RedTeamHarness-verify-p006-20261011`, with that worktree's own `hadagent/src` on `PYTHONPATH`. This is an independent AI check, not a message or approval from the project's designated OpenCode/reviewer roles.

- **MEASURED targeted result:** seven tests passed in 4.65 seconds; each completed 64 passing examples with zero failing examples.
- **MEASURED full-suite result:** 178 tests passed in 15.18 seconds.
- The tracked checkout was clean before and after. Import locations matched the verification worktree. HadAgent and `core` trees were unchanged from the parent commit.
- Test Git blob: `49004b8947b7bb97a464e9aac3cb417dfb3c0543`. The canonical committed-blob SHA-256 matches the value above; the Windows CRLF checkout has a different file hash but the same Git clean-filter identity.
- Independent targeted log SHA-256: `E59A71F3D592BB1235FD9620F4D3D2AB38EA16859A2CF6BBEB72B71227B2DBFE`.
- Independent full-suite log SHA-256: `CE07EC587CE5DC5E3B5BACBC0B53559A246EF0130B3BB564635664F1718B188D`.
- Independent environment/provenance log SHA-256: `15CE4318B2FD417233E4C60A94F129879F533FA7B00370D48029BC4AFBA9A739`.

The detailed report and raw logs are retained under `School_Work/Boyang_Survey/CRA_2026/Proposed_Revisions_2026-10-10/review_1000/`: `P006_INDEPENDENT_CHECK_2026-10-11.md` and `p006_independent_logs_2026-10-11/`. All generated inputs remain **SIMULATED**. No new finding, real-model measurement, or security guarantee follows. The suite was implemented by an AI agent on October 11 under Matthew's instruction; this does not establish that Matthew personally authored it or ran it before that date.

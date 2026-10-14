# P-009 offline block-path preregistration

## Status

**Draft implementation only; no P-009 test has been executed.** This file freezes the inputs, source snapshot, decision oracles, boundaries, and review questions before any measurement. The branch is `astra/block-path-20261011`, based on P-006 commit `279eeb0e2d50237a02d70298117db12c07ab23cb`.

The test source is `hadagent/tests/test_podl_block_path.py`. It adds no dependency and changes no file under `hadagent/src`, `core`, the survey, or the CRA packet.

## Question and paired design

The primary experiment asks whether the already-confirmed synthetic R1 score-rule case and its three Task-1 controls produce the preregistered decisions when they pass through the original `Block.validate` call path. The path uses genuine local record signatures, record hashes, lane Merkle roots, a signed block header, block serialization/deserialization, eval-set hashing/parsing, and the repository's normalized-prefix scorer. Only the absent eval-file bytes and model-completion boundary are replaced with synthetic fixtures.

For each case, the test constructs and signs a complete block once and serializes it once. The original and modified legs each receive a fresh deserialization of those identical bytes. The test asserts the bytes before and after each validation, clears every observation between legs, and never rewrites the payload, scale, claim, record signature, root, header, or producer signature.

The first leg asserts that `podl_chain.block.verify_podl_llm_eval` is the original `podl_chain.pdl.verify_podl_llm_eval` object and leaves that call site untouched. The paired repair leg binds only that imported reference, inside the test, directly to the exact existing `core.podl_verifier.verify_podl_llm_eval_fixed_scale` function object. It does not use a verifier wrapper, verifier lambda, duplicate verifier, or source edit. This is a **modified integration through the unmodified `Block.validate` method**. It is not HadAgent source, upstream behavior, or evidence that deployed/local blocks already use the proposal.

All fixtures are local. `urllib.request.urlopen`, `socket.socket`, and `socket.create_connection` are patched to fail the test. No server, real model, model weights, peer, chain, or third-party service is used.

## Frozen inputs and oracles

The eval set contains exactly 100 synthetic prompt/answer pairs. The synthetic completion returns the exact answer for the first `correct` rows and a distinct non-prefix string for the rest. The production function named `score_exact_match` actually uses `normalize(output).startswith(normalize(answer))`; the fixture proves every intended wrong output fails that predicate and observes the count returned by the real scorer. Each leg must observe exactly one eval load, 100 ordered completion calls, and one scorer result equal to the frozen `correct` value. Result assertions use Boolean identity plus exact reason-string equality, so integer lookalikes cannot satisfy the Boolean oracle.

The block threshold remains the source constant 8,000. The decode configuration remains `temperature=0.0`, `top_k=1`, `top_p=1.0`, `max_tokens=64`, `stop=None`. Timestamp, signing seeds, endpoint placeholder, proof identifiers, and artifact strings are fixed in the test source.

### Primary four Task-1 cases

| Case | Correct / 100 | Payload scale | Claim | Original `Block.validate` | Modified integration |
|---|---:|---:|---:|---|---|
| `ordinary_pass` | 85 | 10,000 | 8,500 | accept, `ok` | accept, `ok` |
| `ordinary_below_target` | 10 | 10,000 | 1,000 | reject, `PoDL failed: score below target (1000 < 8000)` | same rejection |
| `confirmed_R1_counterexample` | 1 | 1,000,000 | 10,000 | accept, `ok` | reject, `PoDL failed: claimed score mismatch (computed 100)` |
| `zero_boundary` | 0 | 1,000,000 | 0 | reject, `PoDL failed: score below target (0 < 8000)` | same rejection |

### Secondary predeclared canonical-threshold controls

These two cases already exist in the fixed-copy unit suite. They are frozen here before execution as a separately labeled secondary set. They do not replace the primary four or add another counterexample search.

| Case | Correct / 100 | Payload scale | Claim | Original `Block.validate` | Modified integration |
|---|---:|---:|---:|---|---|
| `canonical_79_below_target` | 79 | 10,000 | 7,900 | reject, `PoDL failed: score below target (7900 < 8000)` | same rejection |
| `canonical_80_at_target` | 80 | 10,000 | 8,000 | accept, `ok` | accept, `ok` |

All Boolean/reason tuples are constants in the test, not post-run interpretations. No case may be added, removed, or tuned after observing results. Malformed records, bad roots, linkage failures, and header failures are covered elsewhere and are not counted here.

The isolated fixed-scale copy still parses the payload's declared scale but ignores its value in the arithmetic. The modified leg therefore tests the exact existing copy only; it does not establish that noncanonical or inconsistent declared units are rejected, and P-009 does not implement a stricter repair.

## Pinned source snapshot

All pins below were captured from base commit `279eeb0e2d50237a02d70298117db12c07ab23cb` before execution.

| File | Git blob | SHA-256 |
|---|---|---|
| `hadagent/src/podl_chain/block.py` | `f8e4b434110f1d87baee3991ebf4149d3dd2e52e` | `6CC37E2BCF5D9EF601C50B24C30C37BC3C630E6CAA162D90F5967BB6263C2F73` |
| `hadagent/src/podl_chain/pdl.py` | `4c55b2dbdee59df4a46bb5274bdee1724f3711eb` | `11758E12BF9952A09DCF1BFD2BB5786D924AE37DA09516EAB4300D5B740AA8DE` |
| `hadagent/src/podl_chain/records.py` | `c9e7695ac0199393cc2ab06aea7fad712ee89ab9` | `766C0379D6624FBF19799CDA9385C4F7E00A4A53BE3CF4B13B27FB94C42E4B2B` |
| `hadagent/src/podl_chain/crypto.py` | `869e9416b4a2d16cda205b80c4374de23b77da34` | `930047AC333A336E249C644A54893AFA3AD9471CD5571E9F0F2A163587B64523` |
| `hadagent/src/podl_chain/merkle.py` | `76c7bc4a7be87c90b62aa26b8ed6e3e62b066a54` | `8D3DC7732D0D35308E77D67AE7AD3799FF5B7D261196A6AE8A43BEA65CFDECA7` |
| `hadagent/tests/record_create.py` | `27ed67af8734c7f2f627a4e189e35138f48aa452` | `DE9044860EF40A28BDC6B91C309654619FDD1D911A9977927EDEF3037C4EE721` |
| `core/podl_verifier.py` | `ae0fd1e5a9e15bc9f53518e9303553ec31eaf219` | `C1351D27791E27C1D3EEB7F9EB694EF530E0AAFAA405DFC1D77C98006F718444` |
| `tests/test_podl_score_scale.py` | `ddac73e00883f2b509eac9e486bd3a16869d8018` | `7BB9A7E62A66F2BAC0044F4E9F0240BAF3E8D09AC0215DBF2FCB0563F6284076` |
| `tests/test_podl_fixed_scale.py` | `ab6a02174993690ace23e0164b546d6de1b41555` | `600BF7B62E3D19269D42101AA2D60B1155AC85BAEAC86D6F18CCDFC1F6C6760F` |

The P-009 test-file SHA-256 must be inserted below after the draft is complete and before execution. Any source, fixture, case, or oracle edit invalidates the pin and requires a new hash plus renewed review.

- `hadagent/tests/test_podl_block_path.py`: `FCFD4F79E9A0197ED39291262D8BB31223BD48E3359AFBED524DE823DD6E0C93`

## What a future run could and could not establish

If the primary original cases match their oracles, the narrow supported result would be: at the pinned copied snapshot, the previously confirmed synthetic score-rule case propagated through genuine signed local records and the original block-validation function to the preregistered local block-valid decision. If the paired cases match, they would show only that, for the exact same signed serialized blocks, the existing proposed verifier copy produces the preregistered decisions when bound at the block module's imported call-site boundary in this test. The 79/80 cases are secondary threshold controls.

After all assertions pass for a case, the test prints one deterministic `P009_RESULT` JSON line. It records the base commit, case group/name, observed correct count, exact original and modified-integration decisions, and SHA-256 values for the test source, serialized block, and synthetic eval bytes. This is console evidence only; the test does not write an artifact file.

Neither result would establish peer or chain acceptance, reward capture, a live exploit, real-model behavior, model identity, deployment relevance, rejection of arbitrary declared units, the authors' private/current revision, or an upstream fix. Any deviation must be preserved and reported without changing cases, strings, or assertions.

## Frozen future commands: not run

From the worktree, with its own `hadagent/src` on `PYTHONPATH` and the existing main-repository virtual environment:

```powershell
$env:PYTHONPATH=(Resolve-Path 'hadagent/src').Path
& '.venv\Scripts\python.exe' -m pytest -q -s hadagent/tests/test_podl_block_path.py
& '.venv\Scripts\python.exe' -m pytest -q
```

Preserve the exact commit, test hash, commands, raw output, exit codes, environment versions, and full-suite output. Designated protocol roles must independently rerun and review wording before any result enters a ledger, paper, or application. Native parallel reviews are supplementary and are not designated OpenCode/reviewer votes.

## Preregistration review questions

1. Do the four primary and two separately labeled threshold cases exactly match their prior unit-level inputs and the existing proposed fixed-copy behavior?
2. Does every original leg leave `block_module.verify_podl_llm_eval` untouched and prove its identity with `pdl.verify_podl_llm_eval`?
3. Does every modified leg bind the block import directly to the exact existing `verify_podl_llm_eval_fixed_scale` object while leaving `Block.validate` and all source files unchanged?
4. Are both legs fresh deserializations of one signed byte string, with explicit byte-equality assertions and observation resets between them?
5. Are the only synthetic data boundaries the absent eval-file bytes and completion function, while parsing, normalized-prefix scoring, hashing, signatures, roots, serialization, and block validation stay real?
6. Do exact eval-load, ordered completion-call, observed-count, Boolean-identity, and reason assertions make any deviation visible?
7. Are the HTTP and socket failure tripwires sufficient, and can any legitimate dependency behavior require a socket inside the test body?
8. Does each post-assertion `P009_RESULT` line contain enough hashes and exact decisions for a later reviewer to reconcile the captured console log?
9. Are the claim boundary, fixed-copy scale caveat, and prohibition on post-result case expansion explicit enough?

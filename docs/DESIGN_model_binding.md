# Design note: binding a result to a model and to work

Matthew Ngoy, with faculty mentorship from Boyang Li, Kean University, Fall 2026.

This note asks what an accepted inference claim means. The HadAgent paper names a model artifact, input, and decoding configuration and describes independent master-node recomputation. The copied prototype signs those fields but verifies the score by querying the proof submitter's endpoint. P010 shows that this local path can accept known correct answers when the named model never runs.

That observation supports an implementation-to-design gap. It does not establish that the full paper design accepts the same strategy, and it does not make every functionally equivalent implementation malicious. A protocol must state which relation it intends to reward.

## Three different bindings

**Claim binding** authenticates what a participant asserted. A signature can bind the signer to a model ID, artifact hash, endpoint, decode hash, score, and timestamp. The copied records provide this property.

**Artifact/result binding** establishes that a result agrees with execution of the artifact named by the claim under the fixed input and configuration. An honest verifier that retrieves the artifact and recomputes the task can check functional equivalence. The copied endpoint verifier does not do that.

**Work and freshness binding** establishes that the rewarded participant performed the required computation for this challenge, after commitment, rather than returning a cache, replay, proxy result, or outsourced answer. Output equality and deterministic recomputation do not prove this physical history by themselves.

The P012 arithmetic repair addresses none of these identity questions. It places the computed score and threshold in the same fixed units. The all-correct lookup control still passes both arms, as it should under a score-only predicate.

## What P010 establishes

The P010 block used mutually agreeing signed MODEL and PROOF metadata, real signatures and lane roots, and actual loopback HTTP. A dictionary participant returned the frozen benchmark's known answers without loading the named Qwen model. The unchanged local `Block.validate` path accepted the block, and the isolated score-unit repair accepted the same endpoint responses.

This is an existence result for a fixed, known benchmark and copied local validator. It is stronger than a mocked return value because it crosses the serialized block and HTTP boundary. It does not test a hidden or post-commit challenge, a second real model, master voting, network consensus, rewards, or arbitrary user requests.

## Candidate mechanisms

No single mechanism below automatically proves every property.

1. **Verifier-controlled recomputation.** Retrieve the committed artifact by content hash and execute the same fixed task independently. This checks functional agreement with the named artifact. Its verification cost can approach the cost of the inference being verified, and it does not prove which party originally performed the work.
2. **Fresh post-commit challenges.** Bind an unpredictable verifier challenge or block context to the proof after the participant commits. This limits precomputation and replay when the challenge space is large enough. It needs a formal timing, sampling, and soundness argument.
3. **Cryptographic proofs of inference.** Prove a computation relation tied to committed weights and inputs. This can give strong functional guarantees, but proof generation and verification costs must be measured for the target model and deployment.
4. **Trusted execution with remote attestation.** Bind code and model measurements to an attested execution environment. This introduces hardware, vendor, firmware, key-management, and side-channel assumptions.
5. **Model fingerprinting or rotating probes.** Use probes selected to distinguish the committed model from candidate substitutes. This is probabilistic detection, not cryptographic proof, and can fail when an adversary recognizes probes or a substitute is functionally equivalent.
6. **Possession checks.** Challenge openings against a weight commitment to show access to parts of an artifact. Possession alone does not prove that the artifact produced a particular result.

## Next defensible experiment

A stronger study would first formalize whether the system promises output correctness, named-model equivalence, fresh participant work, or all three. It would then use a verifier-controlled committed artifact, a post-commit held-out challenge, an eligible honest baseline, and at least one real substitute plus cache/lookup control. Raw output equality, aggregate score equality, eligibility, participant cost, verifier cost, and decision should be reported separately.

Testing consensus requires the actual master voting and finalization path. Until that implementation is available, results should say “accepted by the copied local validator” rather than “accepted by HadAgent consensus.”

See [P010 results](P010_LOCAL_REDTEAM_RESULTS.md), [P012 results](P012_SCORE_SCALE_GRID_RESULTS.md), and [Scope and claims](SCOPE_AND_CLAIMS.md) for the completed evidence and limits.

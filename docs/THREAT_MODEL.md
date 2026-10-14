# Threat model for the HadAgent verification study

**Project lead:** Matthew Ngoy

**Faculty mentor:** Boyang Li

**Updated:** October 14, 2026

This threat model separates the HadAgent paper's intended system, the copied `podl_chain` snapshot, and the project's independent `core/poi` simulation. The completed experiments measure selected local verification boundaries. They do not exercise a deployed chain or the complete agentic framework.

## System and evidence boundaries

The HadAgent paper proposes useful deterministic inference in place of hash-puzzle mining. It describes DATA, MODEL, and PROOF records; master and secondary nodes; independent recomputation and voting; a ledger; and an agent-serving harness with trust tiers. The design assumes fixed model weights, inputs, decoding settings, and retrievable content-addressed artifacts.

The copied snapshot implements signed records, per-lane Merkle roots, block validation, a local file-backed ledger, a record pool, basic TCP packet transport, and an endpoint-based score check. Its verifier sends the local evaluation prompts to the endpoint named in the proof. The copied source does not include the paper's independent master-voting path, fork choice, rewards, or full trust/serving pipeline.

The separate `core/poi` package simulates trust transitions, optimistic serving, anomaly detection, and candidate defenses. Those components support controlled demonstrations; they are not measurements of the copied HadAgent code.

## Protected properties

The analysis keeps these properties distinct:

1. **Record integrity:** signed MODEL and PROOF assertions cannot be changed undetected.
2. **Block integrity:** record validity, lane roots, linkage fields, and producer signature satisfy the local acceptance rules.
3. **Score validity:** endpoint responses produce the claimed score under the declared scoring rule and units.
4. **Artifact/result binding:** the accepted result agrees with execution of the named model artifact and fixed configuration.
5. **Fresh work and attribution:** the rewarded participant performed the required computation for this challenge rather than replaying, caching, outsourcing, or proxying it.
6. **Distributed agreement:** honest masters reach the intended vote/finality decision under network and Byzantine faults.
7. **Serving safety:** consumer agents receive outputs only under the intended verification and trust policy.

A signature supports integrity of an assertion; it does not prove that the assertion is true. A matching score supports one functional check; it does not establish a unique model or fresh physical work.

## Actors and capabilities

- **Dishonest proof submitter:** can choose signed proof fields allowed by the schema, control the submitted endpoint, know a public evaluation set, cache answers, or serve a different implementation.
- **Dishonest record submitter:** can submit individually valid MODEL and PROOF records with inconsistent metadata.
- **Faulty or adversarial peer:** can replay records or blocks, reorder messages, or submit malformed packets. Network consensus behavior remains outside the current implementation and evidence.
- **Honest but heterogeneous participant:** may use an allowed model/runtime environment whose outputs differ. The current evidence includes one paired CPU configuration, not a heterogeneous-hardware study.
- **Dishonest serving node:** may behave well during a trust-building period and later return unsafe content. This is explored only in the separate synthetic simulation.

## Evaluated cases

| Case | Property tested | Completed evidence | Limits |
|---|---|---|---|
| Participant-controlled score units | Score validity | P012 original accepted 70/78 constructed below-threshold cases; isolated fixed-scale repair accepted 0/78 and retained 6/6 eligible synthetic controls | Finite synthetic grid; no model, consensus, or deployed impact |
| Known-answer endpoint | Artifact/result and work binding | P010/P012 show the copied local score path can accept correct lookup answers without the named model running | Public known benchmark; does not test paper's independent masters or freshness challenge |
| Honest repeated execution | Local functional agreement | P013 produced identical parsed text for 100/100 paired requests and score 2800 in both phases | One CPU configuration; block was truthfully ineligible, so false rejection is undefined |
| Cross-record metadata mismatch | Record relationships | HTTP and ledger extensions accepted independently valid MODEL/PROOF metadata that disagreed | Source does not specify a one-to-one pairing rule; protocol violation is not assumed |
| Replay and linkage | Local block/ledger integrity | Local append rejected wrong height/prior hash; a valid proof could be reused in a newly signed linked block | No peer consensus, voting, finality, or reward path |
| Historical tuple handling | Record validation | Regression reproduces an already-fixed historical caller bug | Not a new finding from this study |

## Hypotheses represented only by simulations

The older top-level runners use fixed or constructed values. They illustrate questions for future measurement:

- output/score divergence across execution configurations;
- trust-then-betray behavior under a simulated optimistic-serving policy;
- lookup and model-substitution scenarios;
- deterministic unsafe-output handling; and
- candidate tolerance, safety-judge, audit, and rotating-challenge defenses.

The simulated percentages, thresholds, compute savings, and safety outcomes are fixture properties. They are not rates measured on HadAgent, real model populations, or deployed systems. Candidate defenses have not received a full protocol or tradeoff evaluation.

## Excluded claims

The current evidence does not establish multi-master safety or liveness, P2P block propagation, fork choice, finality, rewards, Sybil resistance, hidden-challenge soundness, cross-hardware determinism, current upstream behavior, or consumer-agent safety. It also does not show that the full HadAgent design is broken.

The implementation-level findings remain useful because the acceptance predicate is where useful-work claims become ledger decisions. See [Scope and claims](SCOPE_AND_CLAIMS.md) for exact source functions and [Application guide](APPLICATION_GUIDE.md) for evidence labels and reproduction paths.

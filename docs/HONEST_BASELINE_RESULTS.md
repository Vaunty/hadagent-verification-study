# Honest signed-block baseline result

**Measured October 11, 2026 from frozen commit `47c742722441779cae6d7a10a7950219d8708818`.** The primary run completed and a separate native AI reviewer passed its saved artifacts with zero failures. The reviewer did not rerun the model, so this is an independently audited primary result rather than an independent model reproduction.

## Measured result

The cached Qwen2.5-1.5B-Instruct Q4_K_M model ran twice through pinned CPU llama.cpp b11514. Each phase used a fresh model-server process, the same decode settings and the same signed proof endpoint. A separate answer-blind proxy forwarded the original HTTP bytes and had no access to benchmark labels.

The unchanged `pdl.score_exact_match` path counted **28/100 normalized-prefix matches** in the claim phase, producing a truthful frozen score of **2800/10000**. The runner serialized and fsynced the signed block before phase two. The unchanged `Block.validate` path then loaded those exact bytes, made 100 new model requests and independently recomputed **28/100**, or **2800/10000**. It returned the preregistered legitimate rejection:

```text
PoDL failed: score below target (2800 < 8000)
```

The block was not eligible for acceptance because its truthful claim was below the fixed threshold. This is an honest below-threshold baseline, not a false rejection.

| Measurement | Claim phase | Validation phase |
|---|---:|---:|
| Attempted / completed / HTTP 200 requests | 100 / 100 / 100 | 100 / 100 / 100 |
| Matches under the target normalized-prefix scorer | 28/100 | 28/100 |
| Scaled score | 2800/10000 | 2800/10000 |
| Outputs that were exactly one uppercase A/B/C/D letter | 1/100 | 1/100 |
| Phase time | 489.256 s | 542.649 s |

The two phases had 100/100 exact generated-text matches, 100/100 normalized-text matches and 100/100 prefix-outcome matches. Twenty-eight items were correct under the target scorer in both phases; 72 were incorrect in both. Their ordered request bodies were byte-identical. Raw JSON response bodies differed on all 100 pairs because llama.cpp included changing response metadata, while the parsed generated text stayed identical. Total wall time was 1039.664 seconds for 200 model requests.

Only 1/100 outputs was a bare answer letter. The helper's name is misleading: it applies a normalized prefix test rather than exact equality. The 28/100 count therefore describes this repository's scorer on these raw completions. It is not standard MMLU accuracy or a general estimate of Qwen quality.

## Rate accounting

This study contains one paired local baseline, not 100 independent protocol trials. Its honest frozen claim failed the eligibility threshold, leaving **zero eligible honest acceptance trials**. A false-rejection rate would have denominator zero and is undefined. Reporting either 0% or 100% would be wrong. The run also supplies no false-positive rate, attack success rate or population stability estimate.

The seven cheap runner tests are engineering checks. They caught orchestration and evidence-handling defects before inference; their pass count is not an experimental outcome or an attack denominator.

## Evidence and independent audit

The final preflight verified the reviewed commit, clean tracked tree, 52 pinned assets, runtime version, absent owned fixture, 6,787,227,648 bytes of available RAM and sufficient disk space. The run's embedded preflight repeated those checks with 6,828,412,928 bytes available. Source registers before and after execution were byte-identical. The owned evaluation fixture was removed only after its final hash matched the pinned source.

The independent read-only artifact audit decoded the frozen block, verified record and producer signatures and lane roots, re-counted both phases under the checked target response and scoring rules, compared every request and parsed response, checked the frozen endpoint/configuration and confirmed cleanup. It reported zero failures. This was native AI review, not human validation or a designated-provider vote.

| Evidence anchor | SHA-256 |
|---|---|
| Frozen plan | `786a22c5ec9c62570c1676709438e5fa125b188f176d6e8eef360aa3498b250d` |
| Final report | `5d240eac0061225410e21567f0efa9b50be561776dd91602b46019dcbd1939d1` |
| Frozen signed block | `36d8e8ec9a6d7db41f5451e2a5baee20d3cc375754586ab9d69e9ebb775a66a6` |
| Before/after source register | `5a85c6095fd8c69981ff19c4242eb07881be0f50dcb316fef6b1766e07ad2182` |
| Final external preflight | `686065ca9b10e04016cdf84760daf841cd2494e8b6e1cb98ed7ee257ba9c4bcb` |
| Independent audit JSON | `4def16c77e90461cbf4dd01faf6cb3feaa9847198548654206b5c153f9cba7c8` |

The primary evidence remains under the ignored `experiments/honest_baseline/local/attempt-02/` directory. The independent audit is `HONEST_BASELINE_INDEPENDENT_CHECK.json` in the CRA review evidence directory.

## Preserved preflight and failed-attempt history

Failed gates were kept instead of erased. The first preflight at commit `24b1805` stopped at 609,525,760 available RAM against the frozen 3 GiB gate. A later preflight at `c806fa9` stopped at 2,056,998,912 bytes for the same reason; another stopped on an expected-commit mismatch. No inference ran in any of those checks. Preflight `a0c92f3` passed with 6,536,036,352 bytes available.

The first authorized run attempt at `a0c92f3` then hit a relative-plan-path bug before preflight, fixture creation, proxy startup or model startup. It made zero benchmark requests. Its native record remains at `attempt-01/ORIGINAL_FAILURE_RECORDED_AFTERWARD.json`, SHA-256 `24d5856cf4a1086e71a58e0702d4ad3735ac3f50dced170dd34f2a21604b18c1`. The bug was fixed and covered through the documented command's full entrypoint before the reviewed `47c7427` attempt. No score-based retry, prompt change, threshold change or extra model run followed the successful attempt.

## Limits and attribution

This result shows exact output and score reproduction for one cached model, one known fixed 100-item benchmark, one decode configuration and two fresh local server processes. It also shows that the unchanged block validator correctly rejected this truthful but ineligible claim. It does not show an accepted honest block, an error rate across runs, behavior on hidden challenges, cross-hardware reproducibility or current upstream behavior.

The signed block names and hashes the intended model artifact, and the runner verified the cached file and owned server command. The copied validator nevertheless re-queries the endpoint recorded in the proof; it does not implement the paper's independent-master re-execution path. This run therefore establishes output and score reproduction in the local harness, not physical proof that the prover freshly executed those weights. It does not test or defeat the paper's full protocol design.

A native Codex AI agent designed and implemented the runner under Matthew Ngoy's direction, executed the primary run and prepared this result. Separate AI reviewers checked the frozen code and audited the completed artifacts. Matthew authorized and directed the work; this document does not attribute the AI implementation, execution or validation to him.

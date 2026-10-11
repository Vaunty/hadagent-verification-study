# P-009 paired local block-path results

## Status and provenance

Measured October 11, 2026 from frozen code/preregistration commit `af6747f11a278b8fce6b3acfd2f644ddf549ec79`, parent `279eeb0e2d50237a02d70298117db12c07ab23cb`. Code, fixtures and exact oracles were committed before either execution. Two native independent AI design reviews preceded execution. Matthew explicitly directed continued research in this session; Astra recorded that local continuation basis separately from outstanding named-role votes. This is not OpenCode/reviewer approval, official findings-ledger promotion, or a paper edit.

All eval rows, model completions, counts, keys, records, and blocks are **SIMULATED**. Validator decisions and test outcomes are **MEASURED**. No real model, inference server, network peer, live chain, external API, installation, push, or merge occurred. `hadagent/src` and `core` are unchanged from the base.

## Measured comparison

Each case signs and serializes one block once. Both legs deserialize identical bytes. The original leg leaves the verifier import untouched; the modified leg binds that one import to the exact existing isolated repaired function. Record validation, signatures, lane roots, block signing/serialization, eval hashing/parsing and the actual normalized-prefix scorer run. Only the missing file and completion boundaries use fixtures; HTTP/socket entry points fail closed.

| Frozen case | Original decision | Modified-integration decision | Block SHA-256 |
|---|---|---|---|
| ordinary_pass | `True: ok` | `True: ok` | `f014a604d8f3444563b56c11def7b02b30ea1ca933d3fc36bde9e60417faf21d` |
| ordinary_below_target | `False: PoDL failed: score below target (1000 < 8000)` | `False: PoDL failed: score below target (1000 < 8000)` | `881f03a3de7d2425e89581ad41485999c5407fbcffa9764e0871d5db3d0b0d57` |
| confirmed_R1_counterexample | `True: ok` | `False: PoDL failed: claimed score mismatch (computed 100)` | `bdc01e7cf0268421e9972a58d5eb75447b4525ab4e615199ba95b59a31fd0452` |
| zero_boundary | `False: PoDL failed: score below target (0 < 8000)` | `False: PoDL failed: score below target (0 < 8000)` | `29f6b19b40631b6cb847b66299c604299a56315d73b4ce5acc0173cab8466a58` |
| canonical_79_below_target | `False: PoDL failed: score below target (7900 < 8000)` | `False: PoDL failed: score below target (7900 < 8000)` | `610b5687804652473c351eb2841494f3eff2c022604ec788a750f287c1120cc9` |
| canonical_80_at_target | `True: ok` | `True: ok` | `16b543bcf641f54e489b1f15ddcac7484ed1849da842cffa25f78f6c90796305` |

The existing counterexample reaches a local block-valid decision. The repaired call site rejects the same bytes for the predeclared score-semantic reason. All five controls retain their decisions. This strengthens integration evidence for the existing finding; it is not a new vulnerability. Six paired comparisons are twelve local decisions, not twelve attacks or an estimated attack rate. Passing these regression tests includes observing the original undesirable acceptance.

## Reproduction

Commands used the executing worktree's own `hadagent/src` on `PYTHONPATH` and the existing main-repository `.venv`:

- `python -m pytest -q -s hadagent/tests/test_podl_block_path.py`: first **MEASURED 6 passed in 0.96s**; independent clean-checkout **6 passed in 0.57s**.
- `python -m pytest -q`: first **MEASURED 184 passed in 12.36s**; independent **184 passed in 12.48s**.

Both ran the identical committed code. Root compared all six JSON records: decisions, observed counts, block/eval hashes and other semantic fields match. The accurately reported source-byte hashes differ solely by LF/CRLF checkout representation. No code change or result tuning occurred. Raw independent logs are UTF-16 text from PowerShell; root parsed them using their BOM rather than altering the evidence.

Test Git blob `19b1c184852225bd12db837f8ae219218718e4d4`; canonical SHA-256 `FCFD4F79E9A0197ED39291262D8BB31223BD48E3359AFBED524DE823DD6E0C93`. Independent Windows CRLF file SHA-256 `E9ED40FF28C7BF031047A9BEE4A3B789B7205C6CCC91C0586DE26C86EE9B412A`; matching Git clean-filter identity. Environment: Python 3.14.4, pytest 9.1.1, Windows 11. The independent tracked checkout stayed clean.

## Preserved evidence

- First targeted log: `C:\Users\matth\OneDrive\Desktop\RedTeamHarness-block-path-20261011\test_results\astra-p009\targeted.txt`; SHA-256 `fcf98e75de1f06052cb890b356b97d346e48372756a4c1bf3a43ff80569bf134`.
- First full-suite log: `C:\Users\matth\OneDrive\Desktop\RedTeamHarness-block-path-20261011\test_results\astra-p009\full_suite.txt`; SHA-256 `aaebe72fcb701881336050422f386c7b37c94e9c6eee3bad7af27d8be230355b`.
- First execution record: `C:\Users\matth\OneDrive\Desktop\RedTeamHarness-block-path-20261011\test_results\astra-p009\execution.json`; SHA-256 `a5d042496d78f7fe640f5471f89b32972d7dcc4e9ac8818a17034d7520e0789a`.
- Independent targeted log: `C:\Users\matth\OneDrive\Desktop\School_Work\Boyang_Survey\CRA_2026\Proposed_Revisions_2026-10-10\review_1000\P009_INDEPENDENT_LOGS_2026-10-11\targeted_pytest.log`; SHA-256 `bf82bf0f09edaff58ab15e121247dccbf5f22deb0c48ea5e7e53258516c5e2da`.
- Independent full-suite log: `C:\Users\matth\OneDrive\Desktop\School_Work\Boyang_Survey\CRA_2026\Proposed_Revisions_2026-10-10\review_1000\P009_INDEPENDENT_LOGS_2026-10-11\full_pytest.log`; SHA-256 `4fe499f1a4f5dfa6cbce13a238b13fdabd8fc8cc536d063587f1ad731973811c`.
- Independent report: `C:\Users\matth\OneDrive\Desktop\School_Work\Boyang_Survey\CRA_2026\Proposed_Revisions_2026-10-10\review_1000\P009_INDEPENDENT_CHECK_2026-10-11.md`; SHA-256 `2e94e5638c6b58592b143a844787d04016ed46e344b74c210e8728a61e223688`.

## Limits and attribution

No model accuracy, model identity, peers/chain, rewards, deployment relevance, author-side revision, or upstream adoption is established. The existing repair ignores inconsistent declared units rather than rejecting them; endpoint/model binding remains unresolved. A strict optional declared-unit guard is a separate repair experiment under an explicit local design assumption, not part of P-009.

AI agents implemented and reran this work on October 11 under Matthew's instruction. Do not claim his earlier unaided coding or firsthand manual execution. His documented historical scope/test choices remain separately supported. Named OpenCode/reviewer paper-promotion checks and Boyang's firsthand significance assessment remain outstanding. The preregistration is retained as a pre-run artifact instead of being rewritten after results.

# P012 finite score-scale grid results

**Status:** primary attempt and a separate clean-checkout AI reproduction completed successfully on October 11, 2026. The frozen implementation was commit `9de5ac566676670fb57165803d0d2387bd73e1af`. A Codex AI agent designed, implemented and executed this local study at Matthew Ngoy's direction. The reproduction and artifact audit agreed on all 220 decisions. Neither run is independent human validation.

## Measured result

The first and only primary attempt evaluated 110 signed synthetic candidates through both validator arms: 220 decisions and 1,100 actual loopback HTTP requests. All 110 paired decisions, reasons, request counts and response patterns matched the preregistered oracles. Each arm received a fresh deserialization of the same signed bytes for its candidate.

| Finite cohort | Candidates | Original accepts | Isolated-repair accepts | Original accept → repair reject |
|---|---:|---:|---:|---:|
| Canonical `scale=10,000` controls | 32 | 6 | 6 | 0 |
| Below-threshold patterns at `scale=20,000` | 26 | 20 | 0 | 20 |
| Below-threshold patterns at `scale=40,000` | 26 | 25 | 0 | 25 |
| Below-threshold patterns at `scale=1,000,000` | 26 | 25 | 0 | 25 |
| **Defined inflation cohort total** | **78** | **70** | **0** | **70** |

The canonical controls exhaust all 32 five-bit response patterns: one with zero correct, five with one, ten with two, ten with three, five with four and one with five. Both arms rejected all 26 canonical below-threshold patterns and accepted all six eligible patterns. The isolated repair therefore had **0 false rejections among the 6 eligible synthetic controls** in this finite cohort. This is not an honest-real-model false-rejection rate.

The no-model lookup participant returned all five labels for mask `31`. The original arm and isolated repair both returned `True, ok`. That negative control matters: the existing repair changes score normalization and threshold arithmetic; it does not establish model execution or identity.

## Evidence boundary

All participant responses, model labels, artifact labels, keys and signed candidates were **SIMULATED** fixtures. The validator decisions were **MEASURED** through the copied `Block.validate` path using actual signatures, lane roots, block serialization, eval parsing, the original normalized-prefix scorer and owned loopback HTTP. No model, inference runtime, mock, external endpoint, peer, ledger, consensus or reward path ran.

These are exhaustive counts for the declared five-item synthetic grid. They are not confidence intervals, population estimates, general exploit rates, deployed-system findings or evidence about an honest model. The modified arm temporarily bound the block module's imported evaluator reference to the pre-existing `core/podl_verifier.py` function; neither HadAgent target source nor the isolated repair changed during the run.

## Artifacts and integrity

- Attempt directory: `experiments/score_scale_grid/local/attempt-01`
- Main report: `report.json`, SHA-256 `a8c567e70bd525b4034055a8bcf945b25d80bc6313ff22e79eb2b89341559d52`
- Replica report: `report.json`, SHA-256 `2116bbf7c8ec67b081b0a0bb11537c957d2da7328a5069f60ccfb1a5d0808d15`
- Independent cross-run audit: `METRICS_GRID_INDEPENDENT_CHECK.json`, SHA-256 `458557c8bddb71016635f5134c70702b7c9ac7acae8d625c21048b6a9d776cce`
- Row ledger: `rows.jsonl`, SHA-256 `beaf17c53a00b5a7093994f2fef2a82fdabdd1dce7773eae91ee3dc5828a16ff`
- Source-hash records before and after: identical files, each SHA-256 `c7a9ec7c4149279565cce554be3b30eab615d784d9f624b9a292f78e9ecb4a49`
- Saved run window: `2026-10-11T10:43:17Z` through `2026-10-11T10:44:08Z` (51 seconds by saved timestamps; 50.84 seconds from artifact creation to final report write)
- Integrity: `post_integrity=ok`; the installed eval fixture was removed; the worktree remained clean; 110 candidate result files, 110 request traces and 110 participant exit records were preserved.

Each run records zero oracle mismatches, zero request-audit mismatches and 1,100 completed requests. The cross-run audit compared semantic decisions and counts because dynamic loopback ports change candidate bytes and hashes across worktrees.

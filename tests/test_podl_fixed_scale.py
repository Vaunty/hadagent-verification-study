"""Compare a proposed fixed-scale copy with the unmodified PoDL verifier.

SIMULATED: eval-set data, fixed scorer counts, claims, scales, and thresholds.
MEASURED on execution: the original and patched functions' decisions. These
tests do not measure model accuracy or establish an upstream/chain-level fix.
"""

import hashlib
import json
from unittest.mock import Mock

import pytest

from podl_chain import pdl
from core.podl_verifier import verify_podl_llm_eval_fixed_scale


@pytest.fixture
def evaluation(monkeypatch, tmp_path):
    """Use real file loading and parsing, a stub scorer, and no HTTP."""
    pairs = [
        (f"synthetic prompt {index}", f"synthetic answer {index}")
        for index in range(100)
    ]
    evalset_bytes = b"".join(
        json.dumps({"prompt": prompt, "answer": answer}).encode("utf-8") + b"\n"
        for prompt, answer in pairs
    )
    evalset_path = tmp_path / "synthetic-evalset.jsonl"
    evalset_path.write_bytes(evalset_bytes)
    payload = {
        "provider": "llama.cpp",
        "endpoint": "http://127.0.0.1:1/not-contacted",
        "evalset_hash": hashlib.sha256(evalset_bytes).digest(),
        "decode_cfg_hash": pdl.DecodeConfig().hash(),
        "score_scale": 10_000,
        "claimed_score_scaled": 8_500,
    }
    score = Mock(return_value=85)
    monkeypatch.setattr(pdl, "score_exact_match", score)

    def forbid_http(*args, **kwargs):
        pytest.fail("This stubbed unit comparison must not make HTTP requests")

    monkeypatch.setattr(pdl.urllib.request, "urlopen", forbid_http)
    return payload, str(evalset_path), score, pairs


@pytest.mark.parametrize(
    "correct, scale, claim, original_result, patched_result",
    [
        pytest.param(
            85, 10_000, 8_500, (True, "ok"), (True, "ok"),
            id="honest_score_unchanged",
        ),
        pytest.param(
            10, 10_000, 1_000,
            (False, "score below target (1000 < 8000)"),
            (False, "score below target (1000 < 8000)"),
            id="low_score_rejection_unchanged",
        ),
        pytest.param(
            1, 1_000_000, 10_000,
            (True, "ok"),
            (False, "claimed score mismatch (computed 100)"),
            id="original_bypass_payload_rejected_by_patched_copy",
        ),
        pytest.param(
            0, 1_000_000, 0,
            (False, "score below target (0 < 8000)"),
            (False, "score below target (0 < 8000)"),
            id="zero_score_rejection_unchanged",
        ),
        pytest.param(
            79, 10_000, 7_900,
            (False, "score below target (7900 < 8000)"),
            (False, "score below target (7900 < 8000)"),
            id="below_threshold_unchanged",
        ),
        pytest.param(
            80, 10_000, 8_000, (True, "ok"), (True, "ok"),
            id="at_threshold_unchanged",
        ),
    ],
)
def test_original_and_patched_verifier(
    evaluation, correct, scale, claim, original_result, patched_result
):
    """Run identical inputs through both functions; the upstream bug remains."""
    payload, evalset_path, score, pairs = evaluation
    payload.update(score_scale=scale, claimed_score_scaled=claim)
    original_payload = payload.copy()
    for verifier, expected in (
        (pdl.verify_podl_llm_eval, original_result),
        (verify_podl_llm_eval_fixed_scale, patched_result),
    ):
        score.reset_mock()
        score.return_value = correct
        valid, reason = verifier(payload, evalset_path, 8_000)
        assert valid is expected[0]
        assert reason == expected[1]
        score.assert_called_once_with(payload["endpoint"], pairs, pdl.DecodeConfig())
        assert payload == original_payload


@pytest.mark.parametrize("scale", [10_000, 1_000_000])
@pytest.mark.parametrize(
    "correct, claim, expected",
    [
        pytest.param(
            1, 100, (False, "score below target (100 < 8000)"),
            id="canonical_low_claim_still_below_target",
        ),
        pytest.param(85, 8_500, (True, "ok"), id="canonical_honest_claim_passes"),
    ],
)
def test_patched_decision_ignores_payload_scale(evaluation, scale, correct, claim, expected):
    """Canonical claims enforce the threshold regardless of the miner's scale."""
    payload, evalset_path, score, pairs = evaluation
    payload.update(score_scale=scale, claimed_score_scaled=claim)
    score.return_value = correct
    valid, reason = verify_podl_llm_eval_fixed_scale(payload, evalset_path, 8_000)
    assert valid is expected[0]
    assert reason == expected[1]
    score.assert_called_once_with(payload["endpoint"], pairs, pdl.DecodeConfig())


@pytest.mark.parametrize(
    "field, value, reason",
    [
        ("provider", "unsupported", "unsupported provider"),
        ("evalset_hash", b"incorrect evalset digest", "evalset hash mismatch"),
        ("decode_cfg_hash", b"incorrect config digest", "decode config hash mismatch"),
    ],
)
def test_patched_copy_preserves_pre_scoring_gates(evaluation, field, value, reason):
    payload, evalset_path, score, _ = evaluation
    payload[field] = value
    for verifier in (pdl.verify_podl_llm_eval, verify_podl_llm_eval_fixed_scale):
        valid, actual_reason = verifier(payload, evalset_path, 8_000)
        assert valid is False
        assert actual_reason == reason
    score.assert_not_called()


@pytest.mark.parametrize(
    "scale, error",
    [
        pytest.param(None, KeyError, id="missing_scale"),
        pytest.param("not-a-scale", ValueError, id="unparseable_scale"),
    ],
)
def test_patched_copy_preserves_scale_field_errors(evaluation, scale, error):
    """Keep direct-call input errors unchanged while ignoring the parsed value."""
    payload, evalset_path, score, pairs = evaluation
    if scale is None:
        del payload["score_scale"]
    else:
        payload["score_scale"] = scale
    for verifier in (pdl.verify_podl_llm_eval, verify_podl_llm_eval_fixed_scale):
        score.reset_mock()
        with pytest.raises(error):
            verifier(payload, evalset_path, 8_000)
        score.assert_called_once_with(payload["endpoint"], pairs, pdl.DecodeConfig())

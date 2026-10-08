"""Unit-level reproduction against HadAgent's unmodified PoDL verifier.

SIMULATED: the eval set, correct counts, scales, claims, and threshold are
fixed fixtures. Only the real verifier's decisions are MEASURED by execution.
No model inference, HTTP request, record validation, or chain acceptance is
tested here. The inflated-scale case intentionally asserts the current bug.
"""

import hashlib
import json
from unittest.mock import Mock

import pytest

from podl_chain import pdl


@pytest.mark.parametrize(
    "correct, score_scale, claimed_score_scaled, expected_valid, expected_reason",
    [
        pytest.param(85, 10_000, 8_500, True, "ok", id="honest_score_passes"),
        pytest.param(
            10,
            10_000,
            1_000,
            False,
            "score below target (1000 < 8000)",
            id="low_score_fails_at_normal_scale",
        ),
        pytest.param(
            1,
            1_000_000,
            10_000,
            True,
            "ok",
            id="BUG_one_correct_of_100_passes_with_inflated_scale",
        ),
        pytest.param(
            0,
            1_000_000,
            0,
            False,
            "score below target (0 < 8000)",
            id="zero_correct_fails_even_with_inflated_scale",
        ),
    ],
)
def test_real_verifier_score_scale(
    monkeypatch,
    correct,
    score_scale,
    claimed_score_scaled,
    expected_valid,
    expected_reason,
):
    """Document current behavior, including acceptance of the BUG case.

    A SIMULATED count of 1 correct in 100, scaled by 1_000_000, passes the
    fixed 8_000 threshold. Acceptance is the bug being reproduced, not the
    desired security property. A fix should make this case fail this test.
    """
    pairs = [
        (f"fixture prompt {index}", f"fixture answer {index}")
        for index in range(100)
    ]
    evalset_bytes = b"".join(
        json.dumps({"prompt": prompt, "answer": answer}).encode("utf-8") + b"\n"
        for prompt, answer in pairs
    )
    evalset_path = "stubbed-evalset.jsonl"
    endpoint = "http://127.0.0.1:1/not-contacted"
    cfg = pdl.DecodeConfig()
    payload = {
        "provider": "llama.cpp",
        "endpoint": endpoint,
        "evalset_hash": hashlib.sha256(evalset_bytes).digest(),
        "decode_cfg_hash": cfg.hash(),
        "score_scale": score_scale,
        "claimed_score_scaled": claimed_score_scaled,
    }

    load_evalset = Mock(return_value=evalset_bytes)
    parse_evalset = Mock(return_value=pairs)
    score = Mock(return_value=correct)
    monkeypatch.setattr(pdl, "load_evalset_bytes", load_evalset)
    monkeypatch.setattr(pdl, "parse_evalset_jsonl", parse_evalset)
    monkeypatch.setattr(pdl, "score_exact_match", score)

    def forbid_http(*args, **kwargs):
        pytest.fail("This stubbed unit reproduction must not make HTTP requests")

    monkeypatch.setattr(pdl.urllib.request, "urlopen", forbid_http)

    valid, reason = pdl.verify_podl_llm_eval(
        payload, evalset_path, required_min_score_scaled=8_000
    )

    # Assert the boolean itself: a (False, reason) tuple is still truthy.
    assert valid is expected_valid
    assert reason == expected_reason
    load_evalset.assert_called_once_with(evalset_path)
    parse_evalset.assert_called_once_with(evalset_bytes)
    score.assert_called_once_with(endpoint, pairs, cfg)

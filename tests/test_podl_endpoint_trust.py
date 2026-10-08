"""Unit reproduction of endpoint trust with a synthetic lookup table.

SIMULATED: prompts, answers, endpoint, claims, and threshold are test fixtures.
MEASURED on execution: verifier decisions and requests reaching the HTTP stub.
Only urlopen is replaced; loading, parsing, scoring, and verification run for
real. The proposed fixed-scale copy is also tested: endpoint trust remains
unresolved. No socket, answer server, benchmark key, or model is used.
"""

import hashlib
import io
import json

import pytest

from podl_chain import pdl
from core.podl_verifier import verify_podl_llm_eval_fixed_scale


@pytest.mark.parametrize(
    "verifier",
    [
        pytest.param(pdl.verify_podl_llm_eval, id="original"),
        pytest.param(verify_podl_llm_eval_fixed_scale, id="proposed_fixed_scale_copy"),
    ],
)
@pytest.mark.parametrize(
    "serve_correct_answers, claimed_score_scaled, expected_valid, expected_reason",
    [
        pytest.param(True, 10_000, True, "ok", id="lookup_table_is_accepted"),
        pytest.param(
            False,
            0,
            False,
            "score below target (0 < 8000)",
            id="wrong_answers_are_rejected",
        ),
    ],
)
def test_verifier_endpoint_trust(
    monkeypatch,
    tmp_path,
    verifier,
    serve_correct_answers,
    claimed_score_scaled,
    expected_valid,
    expected_reason,
):
    """The HTTP stub answers from the same synthetic eval set, without inference."""
    pairs = [
        (f"synthetic prompt {index}", f"synthetic answer {index}")
        for index in range(5)
    ]
    lookup = dict(pairs)
    evalset_bytes = b"".join(
        json.dumps({"prompt": prompt, "answer": answer}).encode("utf-8") + b"\n"
        for prompt, answer in pairs
    )
    evalset_path = tmp_path / "synthetic-evalset.jsonl"
    evalset_path.write_bytes(evalset_bytes)
    endpoint = "http://127.0.0.1:1/synthetic-lookup-not-contacted"
    payload = {
        "provider": "llama.cpp",
        "endpoint": endpoint,
        "evalset_hash": hashlib.sha256(evalset_bytes).digest(),
        "decode_cfg_hash": pdl.DecodeConfig().hash(),
        "score_scale": 10_000,
        "claimed_score_scaled": claimed_score_scaled,
    }
    requested_prompts = []

    def lookup_response(request, *, timeout):
        assert request.full_url == endpoint
        assert request.get_method() == "POST"
        assert request.get_header("Content-type") == "application/json"
        assert timeout == 120
        body = json.loads(request.data)
        prompt = body["prompt"]
        assert body == {
            "prompt": prompt,
            "temperature": 0.0,
            "top_k": 1,
            "top_p": 1.0,
            "n_predict": 64,
        }
        assert prompt in lookup
        requested_prompts.append(prompt)
        answer = lookup[prompt] if serve_correct_answers else "deliberately wrong"
        return io.BytesIO(json.dumps({"content": answer}).encode("utf-8"))

    monkeypatch.setattr(pdl.urllib.request, "urlopen", lookup_response)

    valid, reason = verifier(
        payload, str(evalset_path), required_min_score_scaled=8_000
    )

    assert valid is expected_valid
    assert reason == expected_reason
    assert requested_prompts == [prompt for prompt, _ in pairs]

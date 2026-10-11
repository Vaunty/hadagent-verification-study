"""P-009 preregistered offline block-path checks for the confirmed R1 case.

DO NOT EXECUTE before P-009 review and approval. All eval rows, completion
outputs, counts, scales, and claims are SIMULATED. If later executed, only the
local block-validator decisions are MEASURED. No model, server, socket, peer,
or live chain is involved.

Each paired test leaves ``block.verify_podl_llm_eval`` untouched for the first
leg. The second leg binds that imported call-site reference directly to the
existing proposed fixed-scale function object. This is a modified-call-site
repair experiment through the unmodified ``Block.validate`` method; it is not
HadAgent source or upstream behavior.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock, call

import pytest

import podl_chain.block as block_module
from core.podl_verifier import verify_podl_llm_eval_fixed_scale
from podl_chain import pdl
from podl_chain.block import Block
from podl_chain.crypto import KeyPair, sha256
from podl_chain.records import Lane, ProofType, Record, make_podl_llm_eval, pack

import record_create as fixtures


FIXED_TIMESTAMP = 1_700_000_000
ENDPOINT = "http://127.0.0.1:1/not-contacted"
EVALSET_SIZE = 100
SOURCE_COMMIT = "279eeb0e2d50237a02d70298117db12c07ab23cb"


@dataclass(frozen=True)
class ScoreCase:
    group: str
    name: str
    correct: int
    score_scale: int
    claimed_score_scaled: int
    original_block: tuple[bool, str]
    repaired_block: tuple[bool, str]


# Primary cases frozen before execution. These are exactly the four Task-1
# inputs, now propagated through Block.validate rather than expanded into new
# counterexample searches.
PRIMARY_CASES = (
    ScoreCase(
        group="primary",
        name="ordinary_pass",
        correct=85,
        score_scale=10_000,
        claimed_score_scaled=8_500,
        original_block=(True, "ok"),
        repaired_block=(True, "ok"),
    ),
    ScoreCase(
        group="primary",
        name="ordinary_below_target",
        correct=10,
        score_scale=10_000,
        claimed_score_scaled=1_000,
        original_block=(False, "PoDL failed: score below target (1000 < 8000)"),
        repaired_block=(False, "PoDL failed: score below target (1000 < 8000)"),
    ),
    ScoreCase(
        group="primary",
        name="confirmed_R1_counterexample",
        correct=1,
        score_scale=1_000_000,
        claimed_score_scaled=10_000,
        original_block=(True, "ok"),
        repaired_block=(
            False,
            "PoDL failed: claimed score mismatch (computed 100)",
        ),
    ),
    ScoreCase(
        group="primary",
        name="zero_boundary",
        correct=0,
        score_scale=1_000_000,
        claimed_score_scaled=0,
        original_block=(False, "PoDL failed: score below target (0 < 8000)"),
        repaired_block=(False, "PoDL failed: score below target (0 < 8000)"),
    ),
)


# Secondary threshold controls frozen separately before execution. They are
# ordinary canonical-scale controls already present in the fixed-copy suite;
# they do not replace or enlarge the primary R1 counterexample set.
SECONDARY_THRESHOLD_CASES = (
    ScoreCase(
        group="secondary_threshold",
        name="canonical_79_below_target",
        correct=79,
        score_scale=10_000,
        claimed_score_scaled=7_900,
        original_block=(False, "PoDL failed: score below target (7900 < 8000)"),
        repaired_block=(False, "PoDL failed: score below target (7900 < 8000)"),
    ),
    ScoreCase(
        group="secondary_threshold",
        name="canonical_80_at_target",
        correct=80,
        score_scale=10_000,
        claimed_score_scaled=8_000,
        original_block=(True, "ok"),
        repaired_block=(True, "ok"),
    ),
)


ALL_CASES = PRIMARY_CASES + SECONDARY_THRESHOLD_CASES


def _signed_proof_record(
    *,
    miner: KeyPair,
    evalset_bytes: bytes,
    score_scale: int,
    claimed_score_scaled: int,
) -> Record:
    signed_fields = {
        "proof_id": sha256(b"p009-block-path-r1-proof"),
        "miner_pk": miner.pubkey_bytes(),
        "base_model_id": "model-1",
        "provider": "llama.cpp",
        "endpoint": ENDPOINT,
        "evalset_hash": sha256(evalset_bytes),
        "decode_cfg_hash": pdl.DecodeConfig().hash(),
        "claimed_score_scaled": claimed_score_scaled,
        "score_scale": score_scale,
        "artifact_hash": sha256(b"p009-synthetic-proof-artifact"),
        "artifact_ref": "local://p009-synthetic-proof",
        "ts": FIXED_TIMESTAMP,
    }
    payload_fields = dict(signed_fields)
    payload_fields["sig"] = miner.sign(pack(signed_fields))
    return Record(
        lane=Lane.PROOF,
        rtype=ProofType.PODL_LLM_EVAL,
        version=1,
        payload=make_podl_llm_eval(**payload_fields),
    )


def _expected_evalset_path() -> str:
    return os.path.abspath(
        os.path.join(
            os.path.dirname(block_module.__file__),
            "..",
            "..",
            "data",
            "evalset",
            "evalset.jsonl",
        )
    )


def _install_synthetic_boundaries(monkeypatch, correct: int):
    pairs = [
        (f"fixture prompt {index}", f"expected answer {index} end")
        for index in range(EVALSET_SIZE)
    ]
    evalset_bytes = b"".join(
        json.dumps({"prompt": prompt, "answer": answer}).encode("utf-8")
        + b"\n"
        for prompt, answer in pairs
    )
    outputs = {
        prompt: answer if index < correct else f"distinct wrong output {index}"
        for index, (prompt, answer) in enumerate(pairs)
    }

    # The repository function is named score_exact_match but implements a
    # normalized-prefix predicate. Passing outputs equal their answers; every
    # intended failure is proved not to satisfy that actual predicate.
    assert all(
        not pdl.normalize_answer(outputs[prompt]).startswith(
            pdl.normalize_answer(answer)
        )
        for index, (prompt, answer) in enumerate(pairs)
        if index >= correct
    )
    fixture_correct = sum(
        pdl.normalize_answer(outputs[prompt]).startswith(
            pdl.normalize_answer(answer)
        )
        for prompt, answer in pairs
    )
    assert fixture_correct == correct

    load_evalset = Mock(return_value=evalset_bytes)
    monkeypatch.setattr(pdl, "load_evalset_bytes", load_evalset)

    def synthetic_completion(endpoint, prompt, cfg):
        assert endpoint == ENDPOINT
        assert cfg == pdl.DecodeConfig()
        return outputs[prompt]

    completion = Mock(side_effect=synthetic_completion)
    monkeypatch.setattr(pdl, "llama_cpp_completion", completion)

    real_scorer = pdl.score_exact_match
    observed_counts: list[int] = []

    def observe_real_scorer(endpoint, scorer_pairs, cfg):
        count = real_scorer(endpoint, scorer_pairs, cfg)
        observed_counts.append(count)
        return count

    monkeypatch.setattr(pdl, "score_exact_match", observe_real_scorer)

    def forbid_network(*args, **kwargs):
        pytest.fail("P-009 offline fixture attempted HTTP or socket access")

    monkeypatch.setattr(pdl.urllib.request, "urlopen", forbid_network)
    monkeypatch.setattr(socket, "socket", forbid_network)
    monkeypatch.setattr(socket, "create_connection", forbid_network)

    return (
        pairs,
        evalset_bytes,
        load_evalset,
        completion,
        observed_counts,
    )


def _build_serialized_block(
    monkeypatch,
    case: ScoreCase,
    evalset_bytes: bytes,
) -> bytes:
    monkeypatch.setattr(fixtures, "now", lambda: FIXED_TIMESTAMP)
    miner = KeyPair.from_seed(sha256(b"p009-synthetic-block-path-miner"))
    producer = KeyPair.from_seed(sha256(b"p009-synthetic-block-path-producer"))
    proof = _signed_proof_record(
        miner=miner,
        evalset_bytes=evalset_bytes,
        score_scale=case.score_scale,
        claimed_score_scaled=case.claimed_score_scaled,
    )
    records = [
        fixtures.valid_data_record(miner),
        fixtures.valid_model_record(miner),
        proof,
    ]
    return fixtures.build_block(records, producer=producer).to_bytes()


def _assert_leg_observations(
    *,
    pairs,
    correct: int,
    load_evalset: Mock,
    completion: Mock,
    observed_counts: list[int],
) -> None:
    assert load_evalset.call_args_list == [call(_expected_evalset_path())]
    assert completion.call_args_list == [
        call(ENDPOINT, prompt, pdl.DecodeConfig()) for prompt, _answer in pairs
    ]
    assert observed_counts == [correct]


def _reset_leg_observations(
    *,
    load_evalset: Mock,
    completion: Mock,
    observed_counts: list[int],
) -> None:
    load_evalset.reset_mock()
    completion.reset_mock()
    observed_counts.clear()


def _assert_exact_result(
    actual: tuple[bool, str],
    expected: tuple[bool, str],
) -> None:
    actual_valid, actual_reason = actual
    expected_valid, expected_reason = expected
    assert actual_valid is expected_valid
    assert actual_reason == expected_reason


@pytest.mark.parametrize(
    "case",
    ALL_CASES,
    ids=lambda case: f"{case.group}__{case.name}",
)
def test_paired_original_and_existing_fixed_copy_block_paths(monkeypatch, case):
    """Compare fresh deserializations of one signed block under both call sites."""

    assert block_module.verify_podl_llm_eval is pdl.verify_podl_llm_eval
    (
        pairs,
        evalset_bytes,
        load_evalset,
        completion,
        observed_counts,
    ) = _install_synthetic_boundaries(monkeypatch, case.correct)

    # Construct and sign once. Both legs receive fresh deserializations of
    # these exact immutable bytes; no payload, signature, or header is rebuilt.
    block_bytes = _build_serialized_block(monkeypatch, case, evalset_bytes)

    original_block = Block.from_bytes(block_bytes)
    assert original_block.to_bytes() == block_bytes
    original_result = original_block.validate(
        expected_prev=b"\x00" * 32,
        expected_height=1,
    )
    _assert_exact_result(original_result, case.original_block)
    assert original_block.to_bytes() == block_bytes
    _assert_leg_observations(
        pairs=pairs,
        correct=case.correct,
        load_evalset=load_evalset,
        completion=completion,
        observed_counts=observed_counts,
    )
    original_observed_correct = observed_counts[0]

    _reset_leg_observations(
        load_evalset=load_evalset,
        completion=completion,
        observed_counts=observed_counts,
    )

    # Modified integration only: bind the imported verifier reference to the
    # exact existing isolated function object. Block.validate itself is intact.
    monkeypatch.setattr(
        block_module,
        "verify_podl_llm_eval",
        verify_podl_llm_eval_fixed_scale,
    )
    assert (
        block_module.verify_podl_llm_eval
        is verify_podl_llm_eval_fixed_scale
    )

    repaired_block = Block.from_bytes(block_bytes)
    assert repaired_block.to_bytes() == block_bytes
    assert repaired_block.to_bytes() == original_block.to_bytes()
    repaired_result = repaired_block.validate(
        expected_prev=b"\x00" * 32,
        expected_height=1,
    )
    _assert_exact_result(repaired_result, case.repaired_block)
    assert repaired_block.to_bytes() == block_bytes
    _assert_leg_observations(
        pairs=pairs,
        correct=case.correct,
        load_evalset=load_evalset,
        completion=completion,
        observed_counts=observed_counts,
    )
    modified_observed_correct = observed_counts[0]

    # A future ``pytest -s`` run emits one deterministic, machine-readable line
    # per frozen case after every oracle and observation assertion has passed.
    result_record = {
        "base_commit": SOURCE_COMMIT,
        "block_sha256": sha256(block_bytes).hex(),
        "case": case.name,
        "case_group": case.group,
        "claimed_score_scaled": case.claimed_score_scaled,
        "evalset_sha256": sha256(evalset_bytes).hex(),
        "modified_integration": {
            "observed_correct": modified_observed_correct,
            "reason": repaired_result[1],
            "valid": repaired_result[0],
        },
        "original": {
            "observed_correct": original_observed_correct,
            "reason": original_result[1],
            "valid": original_result[0],
        },
        "score_scale": case.score_scale,
        "test_source_sha256": sha256(Path(__file__).read_bytes()).hex(),
    }
    print(
        "P009_RESULT "
        + json.dumps(result_record, sort_keys=True, separators=(",", ":"))
    )

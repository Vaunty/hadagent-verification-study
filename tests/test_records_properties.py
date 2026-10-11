"""Deterministic P-006 properties for HadAgent records and block validation.

All keys and record contents are synthetic test data.  These tests exercise the
real ``podl_chain.records`` validators and, for blocks containing only DATA and
MODEL records, the real ``Block.validate`` call site.  PROOF-record schema and
signature validation is covered here, but PoDL scoring semantics are explicitly
outside P-006's block-level scope.

The local truthy-tuple shim below models a bug pattern credited in the project
record to the HadAgent authors' already-fixed commit a4ec9da.  It is not a
checkout or execution of that historical source revision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from hypothesis import given, settings, strategies as st

from podl_chain.block import Block, BlockHeader
from podl_chain.crypto import KeyPair
from podl_chain.records import (
    DataType,
    Lane,
    ModelType,
    ProofType,
    Record,
    make_model_commit,
    make_ownership_commit,
    make_podl_llm_eval,
    pack,
    unpack,
    validate_record,
)


P006_SETTINGS = {
    "max_examples": 64,
    "derandomize": True,
    "database": None,
    "deadline": timedelta(seconds=1),
}

BYTES32 = st.binary(min_size=32, max_size=32)
KEY_SEED = BYTES32
ASCII_TEXT = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=32,
)
NONNEGATIVE_INT = st.integers(min_value=0, max_value=2**31 - 2)
POSITIVE_INT = st.integers(min_value=1, max_value=2**31 - 2)


@dataclass(frozen=True)
class RecordCase:
    kind: str
    record: Record
    authenticated_fields: tuple[str, ...]


@dataclass(frozen=True)
class NonPodlBlockCase:
    records: tuple[Record, ...]
    producer_seed: bytes
    height: int
    previous_hash: bytes
    timestamp: int
    invalid_index: int


@st.composite
def data_record_cases(draw) -> RecordCase:
    signer = KeyPair.from_seed(draw(KEY_SEED))
    signed_fields = {
        "data_id": draw(BYTES32),
        "owner_pk": signer.pubkey_bytes(),
        "content_hash": draw(BYTES32),
        "policy_hash": draw(BYTES32),
        "storage_ref": draw(ASCII_TEXT),
        "ts": draw(NONNEGATIVE_INT),
    }
    payload_fields = dict(signed_fields)
    payload_fields["sig"] = signer.sign(pack(signed_fields))
    record = Record(
        lane=Lane.DATA,
        rtype=DataType.OWNERSHIP_COMMIT,
        version=1,
        payload=make_ownership_commit(**payload_fields),
    )
    return RecordCase("data", record, tuple(signed_fields))


@st.composite
def model_record_cases(draw) -> RecordCase:
    signer = KeyPair.from_seed(draw(KEY_SEED))
    signed_fields = {
        "model_id": draw(ASCII_TEXT),
        "artifact_hash": draw(BYTES32),
        "owner_pk": signer.pubkey_bytes(),
        "storage_ref": draw(ASCII_TEXT),
        "ts": draw(NONNEGATIVE_INT),
    }
    payload_fields = dict(signed_fields)
    payload_fields["sig"] = signer.sign(pack(signed_fields))
    record = Record(
        lane=Lane.MODEL,
        rtype=ModelType.MODEL_COMMIT,
        version=1,
        payload=make_model_commit(**payload_fields),
    )
    return RecordCase("model", record, tuple(signed_fields))


@st.composite
def proof_record_cases(draw) -> RecordCase:
    signer = KeyPair.from_seed(draw(KEY_SEED))
    score_scale = draw(POSITIVE_INT)
    signed_fields = {
        "proof_id": draw(BYTES32),
        "miner_pk": signer.pubkey_bytes(),
        "base_model_id": draw(ASCII_TEXT),
        "provider": draw(ASCII_TEXT),
        "endpoint": draw(ASCII_TEXT),
        "evalset_hash": draw(BYTES32),
        "decode_cfg_hash": draw(BYTES32),
        "claimed_score_scaled": draw(
            st.integers(min_value=0, max_value=score_scale)
        ),
        "score_scale": score_scale,
        "artifact_hash": draw(BYTES32),
        "artifact_ref": draw(ASCII_TEXT),
        "ts": draw(NONNEGATIVE_INT),
    }
    payload_fields = dict(signed_fields)
    payload_fields["sig"] = signer.sign(pack(signed_fields))
    record = Record(
        lane=Lane.PROOF,
        rtype=ProofType.PODL_LLM_EVAL,
        version=1,
        payload=make_podl_llm_eval(**payload_fields),
    )
    return RecordCase("proof", record, tuple(signed_fields))


VALID_RECORD_CASES = st.one_of(
    data_record_cases(),
    model_record_cases(),
    proof_record_cases(),
)
NON_PODL_RECORD_CASES = st.one_of(data_record_cases(), model_record_cases())


@st.composite
def non_podl_block_cases(draw) -> NonPodlBlockCase:
    cases = draw(
        st.lists(NON_PODL_RECORD_CASES, min_size=1, max_size=6)
    )
    return NonPodlBlockCase(
        records=tuple(case.record for case in cases),
        producer_seed=draw(KEY_SEED),
        height=draw(st.integers(min_value=0, max_value=10_000)),
        previous_hash=draw(BYTES32),
        timestamp=draw(NONNEGATIVE_INT),
        invalid_index=draw(st.integers(min_value=0, max_value=len(cases) - 1)),
    )


def _change_same_shape(value):
    """Change a signed value while preserving its validated type and size."""

    if isinstance(value, bytes):
        assert value
        return bytes([value[0] ^ 1]) + value[1:]
    if isinstance(value, str):
        assert value
        first = 33 + ((ord(value[0]) - 33 + 1) % 94)
        return chr(first) + value[1:]
    if type(value) is int:
        # Adjacent XOR pairs stay within the same non-negative MessagePack
        # integer-width bucket, including each boundary used by the strategy.
        return value ^ 1
    raise AssertionError(f"unsupported authenticated value type: {type(value)!r}")


def _replace_payload(record: Record, payload_obj: dict) -> Record:
    return Record(
        lane=record.lane,
        rtype=record.rtype,
        version=record.version,
        payload=pack(payload_obj),
    )


def _mutate_payload_field(record: Record, field: str) -> Record:
    payload_obj = unpack(record.payload)
    payload_obj[field] = _change_same_shape(payload_obj[field])
    return _replace_payload(record, payload_obj)


def _mutate_signature(record: Record) -> Record:
    payload_obj = unpack(record.payload)
    signature = bytearray(payload_obj["sig"])
    signature[0] ^= 1
    payload_obj["sig"] = bytes(signature)
    return _replace_payload(record, payload_obj)


def _drop_payload_field(record: Record, field: str) -> Record:
    payload_obj = unpack(record.payload)
    del payload_obj[field]
    return _replace_payload(record, payload_obj)


def _assert_record_contract(case: RecordCase) -> None:
    valid, reason = validate_record(case.record)
    assert valid is True, f"generated {case.kind} record rejected: {reason}"
    assert reason == "ok"

    for field in case.authenticated_fields:
        changed = _mutate_payload_field(case.record, field)
        changed_valid, changed_reason = validate_record(changed)
        assert changed_valid is False, (
            f"{case.kind}.{field} changed without re-signing was accepted"
        )
        assert "signature" in changed_reason

    changed_signature = _mutate_signature(case.record)
    signature_valid, signature_reason = validate_record(changed_signature)
    assert signature_valid is False, f"{case.kind} signature mutation was accepted"
    assert "signature" in signature_reason

    for field in (*case.authenticated_fields, "sig"):
        missing = _drop_payload_field(case.record, field)
        missing_valid, missing_reason = validate_record(missing)
        assert missing_valid is False, f"missing {case.kind}.{field} was accepted"
        assert missing_reason == f"missing field: {field}"


@settings(**P006_SETTINGS)
@given(case=data_record_cases())
def test_generated_data_records_and_authenticated_mutations(case):
    _assert_record_contract(case)


@settings(**P006_SETTINGS)
@given(case=model_record_cases())
def test_generated_model_records_and_authenticated_mutations(case):
    _assert_record_contract(case)


@settings(**P006_SETTINGS)
@given(case=proof_record_cases())
def test_generated_proof_records_and_authenticated_mutations(case):
    _assert_record_contract(case)


UNSUPPORTED_VERSION = st.one_of(
    st.integers(min_value=-8, max_value=0),
    st.integers(min_value=2, max_value=8),
)
UNSUPPORTED_LANE = st.one_of(
    st.integers(min_value=-8, max_value=0),
    st.integers(min_value=4, max_value=8),
)
UNSUPPORTED_RTYPE = st.one_of(
    st.integers(min_value=-8, max_value=0),
    st.integers(min_value=2, max_value=8),
)


@settings(**P006_SETTINGS)
@given(
    case=VALID_RECORD_CASES,
    bad_version=UNSUPPORTED_VERSION,
    bad_lane=UNSUPPORTED_LANE,
    bad_rtype=UNSUPPORTED_RTYPE,
)
def test_invalid_record_envelope_metadata_is_rejected(
    case,
    bad_version,
    bad_lane,
    bad_rtype,
):
    wrong_version = Record(
        case.record.lane,
        case.record.rtype,
        bad_version,
        case.record.payload,
    )
    version_valid, version_reason = validate_record(wrong_version)
    assert version_valid is False
    assert version_reason == f"unsupported record version: {bad_version}"

    wrong_lane = Record(
        bad_lane,
        case.record.rtype,
        case.record.version,
        case.record.payload,
    )
    lane_valid, lane_reason = validate_record(wrong_lane)
    assert lane_valid is False
    assert lane_reason.startswith("unknown record type:")

    wrong_type = Record(
        case.record.lane,
        bad_rtype,
        case.record.version,
        case.record.payload,
    )
    type_valid, type_reason = validate_record(wrong_type)
    assert type_valid is False
    assert type_reason.startswith("unknown record type:")


def _build_signed_block(case: NonPodlBlockCase, records: list[Record]) -> Block:
    producer = KeyPair.from_seed(case.producer_seed)
    data_root, model_root, proof_root = Block.compute_lane_roots(records)
    unsigned_header = BlockHeader(
        version=1,
        height=case.height,
        prev_hash=case.previous_hash,
        data_root=data_root,
        model_root=model_root,
        proof_root=proof_root,
        ts=case.timestamp,
        producer_pk=producer.pubkey_bytes(),
        sig=b"",
    )
    return Block(
        header=BlockHeader(
            version=unsigned_header.version,
            height=unsigned_header.height,
            prev_hash=unsigned_header.prev_hash,
            data_root=unsigned_header.data_root,
            model_root=unsigned_header.model_root,
            proof_root=unsigned_header.proof_root,
            ts=unsigned_header.ts,
            producer_pk=unsigned_header.producer_pk,
            sig=producer.sign(unsigned_header.signing_bytes()),
        ),
        records=records,
    )


@settings(**P006_SETTINGS)
@given(case=non_podl_block_cases())
def test_real_block_validator_accepts_generated_non_podl_blocks(case):
    assert all(record.lane in (Lane.DATA, Lane.MODEL) for record in case.records)
    block = _build_signed_block(case, list(case.records))
    round_tripped = Block.from_bytes(block.to_bytes())

    valid, reason = round_tripped.validate(
        expected_prev=case.previous_hash,
        expected_height=case.height,
    )

    assert valid is True, reason
    assert reason == "ok"


@settings(**P006_SETTINGS)
@given(case=non_podl_block_cases())
def test_real_block_validator_rejects_invalid_non_podl_record(case):
    records = list(case.records)
    records[case.invalid_index] = _mutate_signature(records[case.invalid_index])
    assert validate_record(records[case.invalid_index])[0] is False

    # Rebuild roots and the producer signature around the invalid record.  A
    # rejection therefore comes from record validation, not stale block data.
    block = _build_signed_block(case, records)
    round_tripped = Block.from_bytes(block.to_bytes())
    valid, reason = round_tripped.validate(
        expected_prev=case.previous_hash,
        expected_height=case.height,
    )

    assert valid is False
    assert reason.startswith("invalid record lane=")
    assert "signature" in reason


def _local_pre_fix_truthy_tuple_shim(records: list[Record]) -> bool:
    """Model the formerly vulnerable pattern; this is not historical source."""

    for record in records:
        # The tuple (False, reason) is truthy, so this condition misses failure.
        if not validate_record(record):
            return False
    return True


@settings(**P006_SETTINGS)
@given(case=non_podl_block_cases())
def test_truthy_tuple_regression_property_distinguishes_real_block(case):
    records = list(case.records)
    invalid = _mutate_signature(records[case.invalid_index])
    records[case.invalid_index] = invalid

    invalid_valid, invalid_reason = validate_record(invalid)
    assert invalid_valid is False
    assert "signature" in invalid_reason

    # The desired property, "invalid records are rejected," is false for the
    # local pre-fix shim and true for the current real Block.validate call site.
    shim_rejects_invalid = not _local_pre_fix_truthy_tuple_shim(records)
    assert shim_rejects_invalid is False

    block = _build_signed_block(case, records)
    real_valid, real_reason = block.validate(
        expected_prev=case.previous_hash,
        expected_height=case.height,
    )
    real_rejects_invalid = real_valid is False
    assert real_rejects_invalid is True
    assert real_reason.startswith("invalid record lane=")
    assert "signature" in real_reason

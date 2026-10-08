"""Proposed score-scale fix in an isolated copy of HadAgent's verifier.

This is an experimental patch, not an upstream fix or the verifier used by
HadAgent's block validation. It reuses the original evaluation helpers and
retains the miner-supplied endpoint: endpoint trust remains unresolved.
"""

from podl_chain import pdl


PROTOCOL_SCORE_SCALE = 10_000


def verify_podl_llm_eval_fixed_scale(
    payload_obj: dict,
    evalset_path: str,
    required_min_score_scaled: int,
) -> tuple[bool, str]:
    """Compare accuracy and the claim in fixed protocol units.

    The payload's score_scale is still parsed, but its value is ignored for
    arithmetic. Both the threshold and claimed_score_scaled use
    PROTOCOL_SCORE_SCALE units. Provider, hash, parsing, scoring, and
    empty-eval-set behavior follow the original copy at 9753f8a; only score
    normalization and threshold arithmetic change.
    """
    if payload_obj["provider"] != "llama.cpp":
        return False, "unsupported provider"

    ebytes = pdl.load_evalset_bytes(evalset_path)
    if pdl.sha256(ebytes) != payload_obj["evalset_hash"]:
        return False, "evalset hash mismatch"

    cfg = pdl.DecodeConfig(
        temperature=0.0,
        top_k=1,
        top_p=1.0,
        max_tokens=64,
        stop=None,
    )
    if cfg.hash() != payload_obj["decode_cfg_hash"]:
        return False, "decode config hash mismatch"

    pairs = pdl.parse_evalset_jsonl(ebytes)
    correct = pdl.score_exact_match(payload_obj["endpoint"], pairs, cfg)
    total = max(1, len(pairs))

    # Preserve the original field-access/conversion behavior, not its units.
    int(payload_obj["score_scale"])
    weighted_correct = correct * PROTOCOL_SCORE_SCALE
    computed_scaled = weighted_correct // total
    if computed_scaled != int(payload_obj["claimed_score_scaled"]):
        return False, f"claimed score mismatch (computed {computed_scaled})"

    if weighted_correct < required_min_score_scaled * total:
        return False, f"score below target ({computed_scaled} < {required_min_score_scaled})"

    return True, "ok"

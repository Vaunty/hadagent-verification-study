"""P012 frozen finite score-scale grid through the copied Block.validate path.

DO NOT EXECUTE before root reviews the frozen commit. The participant is an
owned loopback lookup server with five SIMULATED answers and no model. Signed
fixtures and responses are SIMULATED; completed validator decisions are
MEASURED. This script estimates no population rate.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "hadagent/src")]

from core.podl_verifier import verify_podl_llm_eval_fixed_scale
from podl_chain import block as block_module
from podl_chain import pdl
from podl_chain.block import Block, BlockHeader
from podl_chain.crypto import KeyPair, sha256
from podl_chain.records import Lane, ModelType, ProofType, Record, pack


BASE_COMMIT = "069f6cce89e75bad32b8e969f7e3fe85dae6194e"
EXPERIMENT_DIR = Path(__file__).resolve().parent
PLAN_PATH = EXPERIMENT_DIR / "plan.json"
FIXTURE_PATH = EXPERIMENT_DIR / "fixtures/evalset.jsonl"
EVAL_PATH = ROOT / "hadagent/data/evalset/evalset.jsonl"
LOCAL_ROOT = EXPERIMENT_DIR / "local"
PARTICIPANT = EXPERIMENT_DIR / "participant.py"

TOTAL = 5
PROTOCOL_SCALE = 10_000
THRESHOLD = 8_000
INFLATED_SCALES = (20_000, 40_000, 1_000_000)
FIXED_TIMESTAMP = 1_791_691_200


@dataclass(frozen=True)
class Case:
    cohort: str
    mask: int
    correct: int
    score_scale: int
    claim: int

    @property
    def case_id(self) -> str:
        return f"{self.cohort}__mask-{self.mask:02d}__k-{self.correct}__scale-{self.score_scale}"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_new(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.lower() in {
            "http_proxy",
            "https_proxy",
            "all_proxy",
            "no_proxy",
            "pythonoptimize",
        }:
            del env[key]
    env["NO_PROXY"] = "*"
    env["PYTHONPATH"] = str(ROOT / "hadagent/src") + os.pathsep + str(ROOT)
    env["PYTHONUTF8"] = "1"
    return env


@contextmanager
def owned_process(command: list[str], folder: Path):
    with (folder / "participant.process.log").open("xb") as output:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=child_env(),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        save_new(folder / "participant.process.json", {"command": command, "pid": process.pid})
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)
            save_new(folder / "participant.exit.json", {"exit_code": process.returncode})


def wait_ready(process: subprocess.Popen, path: Path) -> int:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("participant exited before readiness")
        if path.exists():
            try:
                ready = json.loads(path.read_text(encoding="utf-8"))
                if ready["host"] != "127.0.0.1" or not 1 <= ready["port"] <= 65_535:
                    raise ValueError("participant readiness record is invalid")
                return int(ready["port"])
            except json.JSONDecodeError:
                pass
        time.sleep(0.05)
    raise TimeoutError("participant readiness deadline exceeded")


def enumerate_cases() -> list[Case]:
    cases: list[Case] = []
    for mask in range(1 << TOTAL):
        correct = mask.bit_count()
        cases.append(
            Case(
                cohort="canonical_controls",
                mask=mask,
                correct=correct,
                score_scale=PROTOCOL_SCALE,
                claim=(correct * PROTOCOL_SCALE) // TOTAL,
            )
        )
        if correct < 4:
            for scale in INFLATED_SCALES:
                cases.append(
                    Case(
                        cohort="inflation_attempts",
                        mask=mask,
                        correct=correct,
                        score_scale=scale,
                        claim=(correct * scale) // TOTAL,
                    )
                )
    if len(cases) != 110:
        raise AssertionError("the frozen grid must contain 110 candidates")
    if sum(case.cohort == "canonical_controls" for case in cases) != 32:
        raise AssertionError("canonical cohort must contain all 32 patterns")
    if sum(case.cohort == "inflation_attempts" for case in cases) != 78:
        raise AssertionError("inflation cohort must contain 78 candidates")
    return cases


def independent_oracle(case: Case, arm: str) -> tuple[bool, str]:
    """Compute the frozen oracle without calling either production verifier."""
    fixed_score = (case.correct * PROTOCOL_SCALE) // TOTAL
    if arm == "original":
        computed = (case.correct * case.score_scale) // TOTAL
        if computed != case.claim:
            return False, f"PoDL failed: claimed score mismatch (computed {computed})"
        if computed < THRESHOLD:
            return False, f"PoDL failed: score below target ({computed} < {THRESHOLD})"
        return True, "ok"
    if arm != "repaired":
        raise ValueError(f"unknown arm: {arm}")
    if fixed_score != case.claim:
        return False, f"PoDL failed: claimed score mismatch (computed {fixed_score})"
    if case.correct * PROTOCOL_SCALE < THRESHOLD * TOTAL:
        return False, f"PoDL failed: score below target ({fixed_score} < {THRESHOLD})"
    return True, "ok"


def validate_plan(plan: dict) -> None:
    expected = plan["expected_finite_counts"]
    checks = {
        "paired_candidates": 110,
        "decisions": 220,
        "http_requests": 1_100,
        "canonical_original_accepts": 6,
        "canonical_repaired_accepts": 6,
        "canonical_eligible_false_rejects_repaired": 0,
        "inflation_original_accepts": 70,
        "inflation_repaired_accepts": 0,
        "inflation_original_accept_repaired_reject": 70,
    }
    if expected != checks:
        raise ValueError("plan finite-count oracle differs from runner constants")
    if plan["base_commit"] != BASE_COMMIT:
        raise ValueError("plan base commit differs")
    if plan["fixture_items"] != TOTAL:
        raise ValueError("plan fixture count differs")
    if plan["protocol_score_scale"] != PROTOCOL_SCALE:
        raise ValueError("plan protocol scale differs")
    if plan["required_min_score_scaled"] != THRESHOLD:
        raise ValueError("plan threshold differs")


def make_signed_candidate(case: Case, endpoint: str, eval_bytes: bytes) -> bytes:
    url = urlsplit(endpoint)
    if not (
        url.scheme == "http"
        and url.hostname == "127.0.0.1"
        and url.port
        and url.path == "/completion"
        and not url.username
        and not url.password
        and not url.query
        and not url.fragment
    ):
        raise ValueError("only an owned loopback completion endpoint is allowed")

    key = KeyPair.from_seed(sha256(b"P012 public deterministic test-only signing key"))
    model_id = "P012-SIMULATED-NO-MODEL"
    artifact_hash = sha256(b"P012 simulated artifact marker; no model exists")
    artifact_ref = "local://p012-simulated-no-model"
    model = {
        "model_id": model_id,
        "artifact_hash": artifact_hash,
        "owner_pk": key.pubkey_bytes(),
        "storage_ref": artifact_ref,
        "ts": FIXED_TIMESTAMP,
    }
    model["sig"] = key.sign(pack(model))
    proof = {
        "proof_id": sha256(case.case_id.encode("utf-8")),
        "miner_pk": key.pubkey_bytes(),
        "base_model_id": model_id,
        "provider": "llama.cpp",
        "endpoint": endpoint,
        "evalset_hash": sha256(eval_bytes),
        "decode_cfg_hash": pdl.DecodeConfig().hash(),
        "claimed_score_scaled": case.claim,
        "score_scale": case.score_scale,
        "artifact_hash": artifact_hash,
        "artifact_ref": artifact_ref,
        "ts": FIXED_TIMESTAMP,
    }
    proof["sig"] = key.sign(pack(proof))
    records = [
        Record(Lane.MODEL, ModelType.MODEL_COMMIT, 1, pack(model)),
        Record(Lane.PROOF, ProofType.PODL_LLM_EVAL, 1, pack(proof)),
    ]
    data_root, model_root, proof_root = Block.compute_lane_roots(records)
    header = BlockHeader(
        version=1,
        height=1,
        prev_hash=bytes(32),
        data_root=data_root,
        model_root=model_root,
        proof_root=proof_root,
        ts=FIXED_TIMESTAMP,
        producer_pk=key.pubkey_bytes(),
        sig=b"",
    )
    header = replace(header, sig=key.sign(header.signing_bytes()))
    raw = Block(header=header, records=records).to_bytes()
    if Block.from_bytes(raw).to_bytes() != raw:
        raise AssertionError("signed candidate is not serialization-stable")
    return raw


def check_source_boundary() -> dict[str, str]:
    paths = sorted((ROOT / "hadagent/src/podl_chain").glob("*.py"))
    paths.extend(
        [
            ROOT / "core/podl_verifier.py",
            Path(__file__),
            PARTICIPANT,
            PLAN_PATH,
            FIXTURE_PATH,
            ROOT / "docs/P012_SCORE_SCALE_GRID_PREREGISTRATION.md",
        ]
    )
    return {str(path.relative_to(ROOT)): digest(path) for path in paths}


def validate_arm(raw: bytes, arm: str) -> tuple[bool, str]:
    original = pdl.verify_podl_llm_eval
    if block_module.verify_podl_llm_eval is not original:
        raise RuntimeError("Block.validate imported evaluator is not the original at arm entry")
    if Path(inspect.getsourcefile(verify_podl_llm_eval_fixed_scale)).resolve() != (
        ROOT / "core/podl_verifier.py"
    ):
        raise RuntimeError("fixed-scale repair was not imported from the existing isolated copy")
    try:
        if arm == "repaired":
            # Test-only callsite replacement. Block.validate and target files stay unchanged.
            block_module.verify_podl_llm_eval = verify_podl_llm_eval_fixed_scale
            if block_module.verify_podl_llm_eval is not verify_podl_llm_eval_fixed_scale:
                raise AssertionError("repair callsite binding failed")
        elif arm != "original":
            raise ValueError(f"unknown arm: {arm}")
        block = Block.from_bytes(raw)
        if block.to_bytes() != raw:
            raise AssertionError("arm did not receive the original signed candidate bytes")
        decision = block.validate(expected_prev=bytes(32), expected_height=1)
        if block.to_bytes() != raw:
            raise AssertionError("validation changed the signed candidate")
        return decision
    finally:
        block_module.verify_podl_llm_eval = original
        if block_module.verify_podl_llm_eval is not pdl.verify_podl_llm_eval:
            raise RuntimeError("original evaluator callsite was not restored")


def read_trace(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def audit_trace(rows: list[dict], case: Case, pairs: list[tuple[str, str]]) -> dict:
    if len(rows) != 10:
        raise AssertionError("each paired candidate must cause ten HTTP requests")
    prompts = [prompt for prompt, _answer in pairs]
    expected_prompts = prompts + prompts
    if [row.get("prompt") for row in rows] != expected_prompts:
        raise AssertionError("HTTP prompts are not two ordered five-item scorer passes")
    if not all(row.get("status") == "ok" for row in rows):
        raise AssertionError("participant trace contains a failed response")
    if not all(row.get("mask") == case.mask for row in rows):
        raise AssertionError("participant mask changed")
    observed = [bool(row.get("observed_prefix_match")) for row in rows]
    expected_bits = [bool(case.mask & (1 << index)) for index in range(TOTAL)]
    if observed != expected_bits + expected_bits:
        raise AssertionError("response pattern differs between validator arms")
    return {
        "all_responses_label": "SIMULATED",
        "expected_correct_per_arm": case.correct,
        "observed_correct_original": sum(observed[:TOTAL]),
        "observed_correct_repaired": sum(observed[TOTAL:]),
        "ordered_two_arm_trace": True,
        "requests": len(rows),
        "trace_sha256": hashlib.sha256(
            "\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows).encode(
                "utf-8"
            )
        ).hexdigest(),
    }


def run_candidate(case: Case, output: Path, eval_bytes: bytes, pairs: list[tuple[str, str]]) -> dict:
    folder = output / "candidates" / case.case_id
    folder.mkdir(parents=True)
    ready = folder / "ready.json"
    trace = folder / "requests.jsonl"
    command = [
        sys.executable,
        "-X",
        "utf8",
        str(PARTICIPANT),
        "--mask",
        str(case.mask),
        "--evalset",
        str(EVAL_PATH),
        "--ready",
        str(ready),
        "--log",
        str(trace),
    ]
    with owned_process(command, folder) as participant:
        port = wait_ready(participant, ready)
        endpoint = f"http://127.0.0.1:{port}/completion"
        raw = make_signed_candidate(case, endpoint, eval_bytes)
        signed_path = folder / "signed_candidate.msgpack"
        with signed_path.open("xb") as stream:
            stream.write(raw)

        original = validate_arm(raw, "original")
        repaired = validate_arm(raw, "repaired")

    request_audit = audit_trace(read_trace(trace), case, pairs)
    original_expected = independent_oracle(case, "original")
    repaired_expected = independent_oracle(case, "repaired")
    row = {
        "case": {
            "claim": case.claim,
            "cohort": case.cohort,
            "correct": case.correct,
            "id": case.case_id,
            "mask": case.mask,
            "mask_bits_item_4_to_0": format(case.mask, "05b"),
            "score_scale": case.score_scale,
        },
        "evidence": {
            "signed_fixture": "SIMULATED",
            "validator_decisions": "MEASURED",
        },
        "original": {
            "decision": list(original),
            "expected": list(original_expected),
            "oracle_matched": original == original_expected,
        },
        "repaired_callsite": {
            "decision": list(repaired),
            "expected": list(repaired_expected),
            "oracle_matched": repaired == repaired_expected,
        },
        "request_audit": request_audit,
        "same_signed_candidate_both_arms": True,
        "signed_candidate_sha256": hashlib.sha256(raw).hexdigest(),
    }
    save_new(folder / "result.json", row)
    if not row["original"]["oracle_matched"] or not row["repaired_callsite"]["oracle_matched"]:
        raise AssertionError(f"frozen oracle mismatch: {case.case_id}")
    return row


def summarize(rows: list[dict]) -> dict:
    strata: dict[str, dict] = {}
    for row in rows:
        case = row["case"]
        key = f"{case['cohort']}__correct-{case['correct']}__scale-{case['score_scale']}"
        bucket = strata.setdefault(
            key,
            {
                "candidates": 0,
                "cohort": case["cohort"],
                "correct": case["correct"],
                "original_accept": 0,
                "original_accept_repaired_reject": 0,
                "repaired_accept": 0,
                "score_scale": case["score_scale"],
            },
        )
        original_accept = bool(row["original"]["decision"][0])
        repaired_accept = bool(row["repaired_callsite"]["decision"][0])
        bucket["candidates"] += 1
        bucket["original_accept"] += int(original_accept)
        bucket["repaired_accept"] += int(repaired_accept)
        bucket["original_accept_repaired_reject"] += int(original_accept and not repaired_accept)

    canonical = [row for row in rows if row["case"]["cohort"] == "canonical_controls"]
    inflation = [row for row in rows if row["case"]["cohort"] == "inflation_attempts"]
    eligible = [row for row in canonical if row["case"]["correct"] >= 4]
    all_correct = next(row for row in canonical if row["case"]["mask"] == 31)
    summary = {
        "boundary": (
            "finite enumerated synthetic cohort; counts and denominators only; no confidence "
            "intervals, population rates, model inference, or honest-real-model false-rejection rate"
        ),
        "canonical_controls": {
            "candidates": len(canonical),
            "eligible": len(eligible),
            "eligible_false_rejects_repaired": sum(
                not row["repaired_callsite"]["decision"][0] for row in eligible
            ),
            "ineligible": sum(row["case"]["correct"] < 4 for row in canonical),
            "original_accept": sum(row["original"]["decision"][0] for row in canonical),
            "repaired_accept": sum(row["repaired_callsite"]["decision"][0] for row in canonical),
        },
        "inflation_attempts": {
            "candidates": len(inflation),
            "original_accept": sum(row["original"]["decision"][0] for row in inflation),
            "original_accept_repaired_reject": sum(
                row["original"]["decision"][0]
                and not row["repaired_callsite"]["decision"][0]
                for row in inflation
            ),
            "repaired_accept": sum(row["repaired_callsite"]["decision"][0] for row in inflation),
        },
        "no_model_all_correct_control": {
            "case_id": all_correct["case"]["id"],
            "meaning": "lookup answers only; acceptance does not establish model execution or identity",
            "original_decision": all_correct["original"]["decision"],
            "repaired_decision": all_correct["repaired_callsite"]["decision"],
        },
        "totals": {
            "decisions": len(rows) * 2,
            "http_requests": sum(row["request_audit"]["requests"] for row in rows),
            "paired_candidates": len(rows),
        },
        "strata_by_correct_count_and_scale": [strata[key] for key in sorted(strata)],
    }
    return summary


def assert_final_counts(summary: dict, plan: dict) -> None:
    measured = {
        "paired_candidates": summary["totals"]["paired_candidates"],
        "decisions": summary["totals"]["decisions"],
        "http_requests": summary["totals"]["http_requests"],
        "canonical_original_accepts": summary["canonical_controls"]["original_accept"],
        "canonical_repaired_accepts": summary["canonical_controls"]["repaired_accept"],
        "canonical_eligible_false_rejects_repaired": summary["canonical_controls"][
            "eligible_false_rejects_repaired"
        ],
        "inflation_original_accepts": summary["inflation_attempts"]["original_accept"],
        "inflation_repaired_accepts": summary["inflation_attempts"]["repaired_accept"],
        "inflation_original_accept_repaired_reject": summary["inflation_attempts"][
            "original_accept_repaired_reject"
        ],
    }
    if measured != plan["expected_finite_counts"]:
        raise AssertionError("measured finite counts differ from the frozen plan")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    if not output.is_relative_to(LOCAL_ROOT.resolve()):
        raise ValueError("output must stay under experiments/score_scale_grid/local")
    output.mkdir(parents=True, exist_ok=False)

    report = {
        "status": "running",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": [],
        "roles": {
            "responses_and_signed_fixtures": "SIMULATED",
            "validation_decisions": "MEASURED after execution",
        },
    }
    save_new(output / "started.json", report)
    created_eval = False
    before_sources: dict[str, str] | None = None
    try:
        if git("status", "--porcelain", "--untracked-files=all"):
            raise RuntimeError("tracked or unignored source must be clean before first execution")
        head = git("rev-parse", "HEAD")
        if subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE_COMMIT, head],
            check=False,
        ).returncode != 0:
            raise RuntimeError("frozen implementation does not descend from the required E5 base")
        plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        validate_plan(plan)
        cases = enumerate_cases()
        eval_bytes = FIXTURE_PATH.read_bytes()
        pairs = pdl.parse_evalset_jsonl(eval_bytes)
        if len(pairs) != TOTAL or len({prompt for prompt, _answer in pairs}) != TOTAL:
            raise RuntimeError("frozen eval fixture is not five unique prompt/answer pairs")
        if EVAL_PATH.exists():
            raise RuntimeError("target eval path already exists; never replace or reuse it")

        report.update(
            {
                "commit": head,
                "fixture_sha256": hashlib.sha256(eval_bytes).hexdigest(),
                "plan_sha256": digest(PLAN_PATH),
            }
        )
        before_sources = check_source_boundary()
        save_new(output / "source_hashes_before.json", before_sources)
        EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with EVAL_PATH.open("xb") as stream:
            stream.write(eval_bytes)
        created_eval = True
        if EVAL_PATH.read_bytes() != eval_bytes:
            raise RuntimeError("installed eval fixture differs byte-for-byte")

        rows_path = output / "rows.jsonl"
        with rows_path.open("x", encoding="utf-8") as row_log:
            for index, case in enumerate(cases, start=1):
                row = run_candidate(case, output, eval_bytes, pairs)
                report["rows"].append(row)
                row_log.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                row_log.flush()
                print(
                    json.dumps(
                        {
                            "candidate": index,
                            "id": case.case_id,
                            "original": row["original"]["decision"],
                            "repaired": row["repaired_callsite"]["decision"],
                        },
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
        report["summary"] = summarize(report["rows"])
        assert_final_counts(report["summary"], plan)
        report["status"] = "ok"
    except (Exception, KeyboardInterrupt) as exc:
        report["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if created_eval:
            try:
                if not EVAL_PATH.resolve().is_relative_to(ROOT.resolve()):
                    raise RuntimeError("owned fixture path escaped the worktree")
                if EVAL_PATH.read_bytes() != FIXTURE_PATH.read_bytes():
                    raise RuntimeError("installed fixture changed; retained for inspection")
                EVAL_PATH.unlink()
                report["eval_fixture_removed"] = True
            except Exception as exc:
                report["status"] = "failed"
                report["cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}
        try:
            after_sources = check_source_boundary()
            save_new(output / "source_hashes_after.json", after_sources)
            clean = not git("status", "--porcelain", "--untracked-files=all")
            if before_sources is None or before_sources != after_sources or not clean:
                raise RuntimeError("source hashes or worktree cleanliness changed")
            report["post_integrity"] = "ok"
        except Exception as exc:
            report["status"] = "failed"
            report["post_integrity"] = {"type": type(exc).__name__, "message": str(exc)}
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report["rows_recorded"] = len(report["rows"])
        report["result_scope"] = (
            "finite synthetic cohort counts only; not an honest-real-model false-rejection rate, "
            "confidence interval, general rate, model-binding result, or deployed-system claim"
        )
        save_new(output / "report.json", report)
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

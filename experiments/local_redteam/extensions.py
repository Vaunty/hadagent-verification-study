"""Preregistered nine-case local HTTP extension to P010.

The experiment invokes the committed ``Block.validate`` implementation without
patching or monkeypatching it.  It uses only an owned loopback HTTP server and
synthetic signed records.  No model inference, peer, ledger, or external chain
is involved.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import inspect
import json
from pathlib import Path
import threading
import time

import run as base


PREREGISTRATION = Path(__file__).resolve().parents[2] / "docs/LOCAL_HTTP_EXTENSION_PREREGISTRATION.md"
PLAN = Path(__file__).with_name("plan.json")
LOCAL_ROOT = Path(__file__).with_name("local").resolve()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tracked_source_hashes() -> dict[str, str]:
    paths = list((base.ROOT / "hadagent/src/podl_chain").glob("*.py"))
    paths += [
        base.ROOT / "core/podl_verifier.py",
        Path(base.__file__).resolve(),
        Path(base.__file__).with_name("participant.py"),
        Path(__file__).resolve(),
        PLAN,
        PREREGISTRATION,
    ]
    return {
        str(path.relative_to(base.ROOT)): base.digest(path)
        for path in sorted(set(paths))
    }


def verify_target_identity() -> None:
    require(
        base.block_module.verify_podl_llm_eval is base.pdl.verify_podl_llm_eval,
        "Block module is not using the committed original verifier",
    )
    expected = {
        Path(base.pdl.__file__).resolve(): base.ROOT / "hadagent/src/podl_chain/pdl.py",
        Path(base.block_module.__file__).resolve(): base.ROOT / "hadagent/src/podl_chain/block.py",
    }
    for observed, wanted in expected.items():
        require(observed == wanted.resolve(), f"module source escaped worktree: {observed}")
    require(
        Path(inspect.getsourcefile(base.Block.validate)).resolve()
        == (base.ROOT / "hadagent/src/podl_chain/block.py").resolve(),
        "Block.validate source escaped worktree",
    )


def canonical_challenge_variant(pairs: list[tuple[str, str]]) -> bytes:
    rows = []
    for prompt, answer in pairs:
        row = {"prompt": prompt + "\nChallenge variant.", "answer": answer}
        rows.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return "".join(rows).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    require(output.is_relative_to(LOCAL_ROOT), "output must stay under experiments/local_redteam/local")
    require(not output.exists(), "output directory already exists")
    require(not base.git("status", "--porcelain", "--untracked-files=no"), "tracked worktree must be clean")
    verify_target_identity()
    output.mkdir(parents=True, exist_ok=False)

    plan = json.loads(PLAN.read_text(encoding="utf-8-sig"))
    eval_source = Path(plan["evalset"]["path"])
    original = eval_source.read_bytes()
    require(sha256_bytes(original) == plan["evalset"]["sha256"], "source evalset hash differs from plan")
    pairs = base.pdl.parse_evalset_jsonl(original)
    require(len(pairs) == 100, "extension requires the frozen 100-item evalset")
    require(len({prompt for prompt, _ in pairs}) == 100, "evalset prompts must be unique")
    lookup = dict(pairs)
    require(
        all(prompt + "\nChallenge variant." not in lookup for prompt, _ in pairs),
        "challenge variant collides with an original prompt",
    )
    challenge = canonical_challenge_variant(pairs)

    # These exact oracles are duplicated in the committed preregistration.
    oracles = {
        "baseline": ([True, "ok"], 100, {"lookup_answer": 100}),
        "signed_artifact_mismatch": ([True, "ok"], 100, {"lookup_answer": 100}),
        "signed_model_id_mismatch": ([True, "ok"], 100, {"lookup_answer": 100}),
        "unsigned_proof_tamper": (
            [False, "invalid record lane=3 type=1: invalid PoDL signature"],
            0,
            {},
        ),
        "repeat_identical_block": ([True, "ok"], 100, {"lookup_answer": 100}),
        "reuse_proof_next_height": ([True, "ok"], 100, {"lookup_answer": 100}),
        "same_signed_block_changed_responses": (
            [False, "PoDL failed: claimed score mismatch (computed 0)"],
            100,
            {"wrong_constant": 100},
        ),
        "changed_challenge_stale_hash": (
            [False, "PoDL failed: evalset hash mismatch"],
            0,
            {},
        ),
        "changed_challenge_signed_hash_stale_lookup": (
            [False, "PoDL failed: claimed score mismatch (computed 0)"],
            100,
            {"unknown_prompt": 100},
        ),
    }

    key = base.KeyPair.from_seed(base.sha256(b"P010 public local experiment key"))
    state: dict[str, object] = {"mode": "lookup", "case": None}
    traces: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            length = int(self.headers.get("Content-Length", "0"))
            raw_request = self.rfile.read(length)
            request = json.loads(raw_request)
            prompt = request.get("prompt")
            mode = state["mode"]
            if mode == "wrong":
                answer, response_kind = "[wrong]", "wrong_constant"
            elif prompt in lookup:
                answer, response_kind = lookup[prompt], "lookup_answer"
            else:
                answer, response_kind = "[unknown]", "unknown_prompt"
            body = json.dumps({"content": answer}, separators=(",", ":")).encode("utf-8")
            traces.append(
                {
                    "case": state["case"],
                    "ordinal": sum(row["case"] == state["case"] for row in traces),
                    "request_body_sha256": sha256_bytes(raw_request),
                    "prompt_sha256": sha256_bytes(str(prompt).encode("utf-8")),
                    "response_kind": response_kind,
                    "response_body_sha256": sha256_bytes(body),
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    source_before = tracked_source_hashes()
    commit = base.git("rev-parse", "HEAD")
    report: dict[str, object] = {
        "experiment": "P010 nine-case local extension",
        "evidence": "MEASURED only where rows contain observed decisions",
        "inputs_and_oracles": "SIMULATED and preregistered",
        "scope": "owned loopback HTTP plus Block.validate; no ledger, peers, chain, or model inference",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "commit": commit,
        "plan_sha256": base.digest(PLAN),
        "preregistration_sha256": base.digest(PREREGISTRATION),
        "implementation_sha256": base.digest(__file__),
        "source_evalset_sha256": sha256_bytes(original),
        "challenge_variant_sha256": sha256_bytes(challenge),
        "rows": [],
    }
    base.save(output / "started.json", report)

    server: HTTPServer | None = None
    thread: threading.Thread | None = None
    fixture_owned = False
    expected_fixture_sha256: str | None = None
    operational_error: BaseException | None = None

    try:
        base.EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        require(not base.EVAL_PATH.exists(), "eval fixture already exists; refusing replacement or reuse")
        with base.EVAL_PATH.open("xb") as handle:
            handle.write(original)
        fixture_owned = True
        expected_fixture_sha256 = sha256_bytes(original)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/completion"

        def make_block(
            changes: dict[str, object] | None = None,
            *,
            resign_proof: bool = True,
            height: int = 1,
            prev: bytes = bytes(32),
            proof_record: base.Record | None = None,
        ) -> base.Block:
            raw = base.signed_block(
                endpoint,
                plan["model"]["sha256"],
                sha256_bytes(base.EVAL_PATH.read_bytes()),
            )
            block = base.Block.from_bytes(raw)
            records = list(block.records)
            if changes:
                proof = base.unpack(records[1].payload)
                proof.update(changes)
                if resign_proof:
                    proof.pop("sig", None)
                    proof["sig"] = key.sign(base.pack(proof))
                records[1] = replace(records[1], payload=base.pack(proof))
            if proof_record is not None:
                records[1] = proof_record
            data_root, model_root, proof_root = base.Block.compute_lane_roots(records)
            header = replace(
                block.header,
                height=height,
                prev_hash=prev,
                data_root=data_root,
                model_root=model_root,
                proof_root=proof_root,
            )
            header = replace(header, sig=key.sign(header.signing_bytes()))
            return base.Block(header, records)

        def measure(
            name: str,
            block: base.Block,
            *,
            expected_prev: bytes = bytes(32),
            expected_height: int = 1,
        ) -> dict[str, object]:
            state["case"] = name
            trace_start = len(traces)
            active_pairs = base.pdl.parse_evalset_jsonl(base.EVAL_PATH.read_bytes())
            expected_prompt_hashes = [sha256_bytes(prompt.encode("utf-8")) for prompt, _ in active_pairs]
            raw = block.to_bytes()
            block_path = output / f"{name}.msgpack"
            block_path.write_bytes(raw)
            row: dict[str, object] = {
                "name": name,
                "measurement_status": "started",
                "block_sha256": sha256_bytes(raw),
                "proof_record_sha256": sha256_bytes(block.records[1].to_bytes()),
                "expected_height": expected_height,
                "expected_prev_sha256": sha256_bytes(expected_prev),
            }
            try:
                decision = list(base.Block.from_bytes(raw).validate(expected_prev, expected_height))
                case_traces = traces[trace_start:]
                response_counts = dict(sorted(Counter(x["response_kind"] for x in case_traces).items()))
                observed_prompt_hashes = [x["prompt_sha256"] for x in case_traces]
                ordered_prompt_prefix = observed_prompt_hashes == expected_prompt_hashes[: len(case_traces)]
                expected_decision, expected_requests, expected_responses = oracles[name]
                row.update(
                    measurement_status="measured",
                    decision=decision,
                    requests=len(case_traces),
                    response_counts=response_counts,
                    ordered_prompt_prefix=ordered_prompt_prefix,
                    request_trace_sha256=sha256_bytes(
                        json.dumps(case_traces, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ),
                    expected_decision=expected_decision,
                    expected_requests=expected_requests,
                    expected_response_counts=expected_responses,
                    oracle_matched=(
                        decision == expected_decision
                        and len(case_traces) == expected_requests
                        and response_counts == expected_responses
                        and ordered_prompt_prefix
                    ),
                )
            except Exception as exc:  # preserve a scientific failure as a row
                row.update(
                    measurement_status="error",
                    error={"type": type(exc).__name__, "message": str(exc)},
                    requests=len(traces) - trace_start,
                    oracle_matched=False,
                )
            report["rows"].append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
            return row

        baseline = make_block()
        baseline_row = measure("baseline", baseline)
        artifact_block = make_block({"artifact_hash": bytes(32)})
        measure("signed_artifact_mismatch", artifact_block)
        model_id_block = make_block({"base_model_id": "uncommitted-model"})
        measure("signed_model_id_mismatch", model_id_block)
        measure(
            "unsigned_proof_tamper",
            make_block({"base_model_id": "uncommitted-model"}, resign_proof=False),
        )
        repeat_row = measure("repeat_identical_block", baseline)
        baseline_hash = baseline.block_hash()
        replay_row = measure(
            "reuse_proof_next_height",
            make_block(height=2, prev=baseline_hash, proof_record=baseline.records[1]),
            expected_prev=baseline_hash,
            expected_height=2,
        )

        state["mode"] = "wrong"
        changed_response_row = measure("same_signed_block_changed_responses", baseline)
        state["mode"] = "lookup"

        base.EVAL_PATH.write_bytes(challenge)
        expected_fixture_sha256 = sha256_bytes(challenge)
        stale_row = measure("changed_challenge_stale_hash", baseline)
        signed_challenge = make_block()
        signed_challenge_row = measure("changed_challenge_signed_hash_stale_lookup", signed_challenge)

        # Relationship checks establish what was actually held equal or changed.
        model_payload = base.unpack(baseline.records[0].payload)
        artifact_payload = base.unpack(artifact_block.records[1].payload)
        model_id_payload = base.unpack(model_id_block.records[1].payload)
        mismatch_records = artifact_block.records + model_id_block.records
        report["relationship_checks"] = {
            "artifact_mismatch_is_real": artifact_payload["artifact_hash"] != model_payload["artifact_hash"],
            "model_id_mismatch_is_real": model_id_payload["base_model_id"] != model_payload["model_id"],
            "mismatch_records_individually_validate": all(
                base.block_module.validate_record(record) == (True, "ok") for record in mismatch_records
            ),
            "repeat_block_bytes_identical": repeat_row["block_sha256"] == baseline_row["block_sha256"],
            "changed_response_block_bytes_identical": changed_response_row["block_sha256"] == baseline_row["block_sha256"],
            "next_height_reused_identical_proof_record": replay_row["proof_record_sha256"]
            == baseline_row["proof_record_sha256"],
            "stale_challenge_reused_baseline_block": stale_row["block_sha256"] == baseline_row["block_sha256"],
            "signed_challenge_block_changed": signed_challenge_row["block_sha256"] != baseline_row["block_sha256"],
            "all_relationship_checks_true": False,
        }
        relationship_values = [
            value
            for key_name, value in report["relationship_checks"].items()
            if key_name != "all_relationship_checks_true"
        ]
        report["relationship_checks"]["all_relationship_checks_true"] = all(relationship_values)

        rows = report["rows"]
        all_measured = len(rows) == 9 and all(row["measurement_status"] == "measured" for row in rows)
        all_oracles = all_measured and all(row["oracle_matched"] for row in rows)
        relationships_ok = report["relationship_checks"]["all_relationship_checks_true"]
        report["execution_status"] = "completed" if all_measured else "failed"
        report["oracle_status"] = "all_matched" if all_oracles else "one_or_more_mismatched"
        if all_measured and relationships_ok and all_oracles:
            report["status"] = "ok"
        elif all_measured and relationships_ok:
            report["status"] = "completed_with_oracle_mismatch"
        else:
            report["status"] = "failed"
    except BaseException as exc:
        operational_error = exc
        report["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        report["execution_status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                report["status"] = "failed"
                report["server_cleanup_error"] = "server thread remained alive"

        base.save(output / "requests.json", traces)
        report["request_log_sha256"] = base.digest(output / "requests.json")

        if fixture_owned:
            try:
                require(base.EVAL_PATH.resolve().is_relative_to(base.ROOT.resolve()), "fixture escaped worktree")
                actual_fixture_sha = base.digest(base.EVAL_PATH)
                report["eval_fixture_final_sha256"] = actual_fixture_sha
                require(actual_fixture_sha == expected_fixture_sha256, "owned eval fixture changed unexpectedly")
                base.EVAL_PATH.unlink()
                report["eval_fixture_removed"] = not base.EVAL_PATH.exists()
                require(report["eval_fixture_removed"], "owned eval fixture still exists after removal")
            except Exception as exc:
                report["status"] = "failed"
                report["cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}

        try:
            source_after = tracked_source_hashes()
            report["source_hashes_before"] = source_before
            report["source_hashes_after"] = source_after
            report["source_integrity_ok"] = source_before == source_after
            report["tracked_worktree_clean_after"] = not base.git(
                "status", "--porcelain", "--untracked-files=no"
            )
            require(report["source_integrity_ok"], "tracked source changed during run")
            require(report["tracked_worktree_clean_after"], "tracked worktree dirty after run")
        except Exception as exc:
            report["status"] = "failed"
            report["post_integrity_error"] = {"type": type(exc).__name__, "message": str(exc)}

        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        base.save(output / "report.json", report)

    if operational_error is not None:
        return 130 if isinstance(operational_error, KeyboardInterrupt) else 1
    return 0 if report.get("status") in {"ok", "completed_with_oracle_mismatch"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

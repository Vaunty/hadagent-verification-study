"""Preregistered local Ledger.append and loopback peer-transport study.

The target implementation is not patched or monkeypatched.  The only network
traffic is between owned 127.0.0.1 servers and clients.  The HTTP participant
serves frozen benchmark answers; no model is loaded.
"""
from __future__ import annotations

import argparse
import asyncio
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

from podl_chain.hub import InformationHub
from podl_chain.ledger import GENESIS_PREV, Ledger
from podl_chain.net import AsyncNodeServer, send_packet_expect_one_response
from podl_chain.packets import Packet, PacketType
from podl_chain.pool import AIPool
from podl_chain.records import Lane, pack, unpack, validate_record


PREREGISTRATION = Path(__file__).resolve().parents[2] / "docs/LOCAL_LEDGER_PEER_PREREGISTRATION.md"
PLAN = Path(__file__).with_name("plan.json")
LOCAL_ROOT = Path(__file__).with_name("local").resolve()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_hashes() -> dict[str, str]:
    paths = list((base.ROOT / "hadagent/src/podl_chain").glob("*.py"))
    paths += [
        base.ROOT / "core/podl_verifier.py",
        Path(base.__file__).resolve(),
        Path(base.__file__).with_name("participant.py"),
        Path(base.__file__).with_name("extensions.py"),
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
        Path(inspect.getsourcefile(Ledger.append)).resolve(): base.ROOT / "hadagent/src/podl_chain/ledger.py",
        Path(inspect.getsourcefile(AsyncNodeServer)).resolve(): base.ROOT / "hadagent/src/podl_chain/net.py",
        Path(inspect.getsourcefile(InformationHub)).resolve(): base.ROOT / "hadagent/src/podl_chain/hub.py",
        Path(inspect.getsourcefile(Packet)).resolve(): base.ROOT / "hadagent/src/podl_chain/packets.py",
    }
    for observed, wanted in expected.items():
        require(observed == wanted.resolve(), f"module source escaped worktree: {observed}")


def ledger_state(ledger: Ledger) -> dict[str, object]:
    directory = Path(ledger.chain_dir)
    files = []
    for path in sorted(directory.glob("*.block")):
        files.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": base.digest(path),
            }
        )
    return {
        "height": ledger.height(),
        "last_hash": ledger.last_hash().hex(),
        "files": files,
    }


async def run_experiment(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    require(output.is_relative_to(LOCAL_ROOT), "output must stay under experiments/local_redteam/local")
    require(not output.exists(), "output directory already exists")
    require(not base.git("status", "--porcelain", "--untracked-files=no"), "tracked worktree must be clean")
    verify_target_identity()
    output.mkdir(parents=True, exist_ok=False)
    blocks_dir = output / "blocks"
    states_dir = output / "states"
    packets_dir = output / "packets"
    ledgers_dir = output / "ledgers"
    for directory in (blocks_dir, states_dir, packets_dir, ledgers_dir):
        directory.mkdir()

    plan = json.loads(PLAN.read_text(encoding="utf-8-sig"))
    source_eval = Path(plan["evalset"]["path"]).read_bytes()
    require(sha256_bytes(source_eval) == plan["evalset"]["sha256"], "source evalset hash differs")
    pairs = base.pdl.parse_evalset_jsonl(source_eval)
    require(len(pairs) == 100, "study requires the frozen 100-item evalset")
    require(len({prompt for prompt, _ in pairs}) == 100, "evalset prompts must be unique")
    lookup = dict(pairs)

    ledger_oracles = {
        "ledger_baseline_genesis": ([True, "appended"], 100, -1, 0),
        "ledger_exact_block_replay": ([False, "height mismatch"], 0, 0, 0),
        "ledger_reuse_proof_next_height": ([True, "appended"], 100, 0, 1),
        "ledger_wrong_prev_at_expected_height": ([False, "prev_hash mismatch"], 0, 1, 1),
        "ledger_signed_artifact_mismatch": ([True, "appended"], 100, -1, 0),
        "ledger_signed_model_id_mismatch": ([True, "appended"], 100, -1, 0),
        "ledger_unsigned_proof_tamper": (
            [False, "invalid record lane=3 type=1: invalid PoDL signature"],
            0,
            -1,
            -1,
        ),
        "peer_records_ledger_append": ([True, "appended"], 100, -1, 0),
    }
    peer_oracles = {
        "tcp_model_submission": ("PONG", True, 0, 1, None, None),
        "tcp_mismatched_proof_submission": ("PONG", True, 1, 2, None, None),
        "tcp_malformed_proof": ("ERROR", False, 2, 2, None, "artifact_hash_hex"),
        "tcp_pool_sync": ("POOL_SYNC_RESPONSE", None, 2, 2, 2, None),
        "tcp_block_announce": ("ERROR", False, 0, 0, None, "Unhandled packet type: BLOCK_ANNOUNCE"),
    }

    key = base.KeyPair.from_seed(base.sha256(b"P010 public local experiment key"))
    http_state: dict[str, object] = {"case": None}
    http_traces: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802 - inherited API
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            request = json.loads(raw)
            prompt = request.get("prompt")
            answer = lookup.get(prompt, "[unknown]")
            response_kind = "lookup_answer" if prompt in lookup else "unknown_prompt"
            body = json.dumps({"content": answer}, separators=(",", ":")).encode("utf-8")
            http_traces.append(
                {
                    "case": http_state["case"],
                    "ordinal": sum(row["case"] == http_state["case"] for row in http_traces),
                    "path": self.path,
                    "request_body_sha256": sha256_bytes(raw),
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

    report: dict[str, object] = {
        "experiment": "P010 local ledger and peer-boundary follow-up",
        "evidence": "MEASURED where rows contain observed decisions or TCP responses",
        "inputs_and_oracles": "SIMULATED and preregistered",
        "scope": "Ledger.append plus one owned loopback TCP hub; no consensus or external network",
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "commit": base.git("rev-parse", "HEAD"),
        "plan_sha256": base.digest(PLAN),
        "preregistration_sha256": base.digest(PREREGISTRATION),
        "implementation_sha256": base.digest(__file__),
        "evalset_sha256": sha256_bytes(source_eval),
        "ledger_rows": [],
        "peer_rows": [],
    }
    base.save(output / "started.json", report)
    source_before = source_hashes()

    fixture_owned = False
    http_server: HTTPServer | None = None
    http_thread: threading.Thread | None = None
    peer_server: AsyncNodeServer | None = None
    operational_error: BaseException | None = None

    try:
        base.EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        require(not base.EVAL_PATH.exists(), "eval fixture already exists; refusing replacement or reuse")
        with base.EVAL_PATH.open("xb") as handle:
            handle.write(source_eval)
        fixture_owned = True

        http_server = HTTPServer(("127.0.0.1", 0), Handler)
        http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        http_thread.start()
        endpoint = f"http://127.0.0.1:{http_server.server_port}/completion"
        report["http_binding"] = {"host": "127.0.0.1", "port": http_server.server_port}

        def make_block(
            changes: dict[str, object] | None = None,
            *,
            resign_proof: bool = True,
            height: int = 0,
            prev: bytes = GENESIS_PREV,
            proof_record: base.Record | None = None,
        ) -> base.Block:
            raw = base.signed_block(
                endpoint,
                plan["model"]["sha256"],
                plan["evalset"]["sha256"],
            )
            block = base.Block.from_bytes(raw)
            records = list(block.records)
            if changes:
                proof = unpack(records[1].payload)
                proof.update(changes)
                if resign_proof:
                    proof.pop("sig", None)
                    proof["sig"] = key.sign(pack(proof))
                records[1] = replace(records[1], payload=pack(proof))
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

        def sign_records(records: list[base.Record], height: int, prev: bytes) -> base.Block:
            data_root, model_root, proof_root = base.Block.compute_lane_roots(records)
            header = base.BlockHeader(
                version=1,
                height=height,
                prev_hash=prev,
                data_root=data_root,
                model_root=model_root,
                proof_root=proof_root,
                ts=base.TS,
                producer_pk=key.pubkey_bytes(),
                sig=b"",
            )
            header = replace(header, sig=key.sign(header.signing_bytes()))
            return base.Block(header, records)

        def append_cell(name: str, ledger: Ledger, block: base.Block) -> dict[str, object]:
            http_state["case"] = name
            trace_start = len(http_traces)
            raw = block.to_bytes()
            block_path = blocks_dir / f"{name}.msgpack"
            block_path.write_bytes(raw)
            before = ledger_state(ledger)
            base.save(states_dir / f"{name}.before.json", before)
            row: dict[str, object] = {
                "name": name,
                "boundary": "Ledger.append",
                "measurement_status": "started",
                "candidate_block_sha256": sha256_bytes(raw),
                "proof_record_sha256": sha256_bytes(block.records[1].to_bytes()),
                "before": before,
            }
            try:
                decision = list(ledger.append(base.Block.from_bytes(raw)))
                after = ledger_state(ledger)
                base.save(states_dir / f"{name}.after.json", after)
                traces = http_traces[trace_start:]
                observed_prompt_hashes = [trace["prompt_sha256"] for trace in traces]
                expected_prompt_hashes = [sha256_bytes(prompt.encode("utf-8")) for prompt, _ in pairs]
                ordered_prompt_prefix = observed_prompt_hashes == expected_prompt_hashes[: len(traces)]
                all_completion_path = all(trace["path"] == "/completion" for trace in traces)
                response_counts = dict(sorted(Counter(trace["response_kind"] for trace in traces).items()))
                expected_decision, expected_requests, expected_before, expected_after = ledger_oracles[name]
                candidate_path = Path(ledger.chain_dir) / f"{block.header.height:016d}.block"
                persisted_candidate = (
                    candidate_path.exists() and sha256_bytes(candidate_path.read_bytes()) == sha256_bytes(raw)
                )
                state_transition_ok = (
                    before["height"] == expected_before
                    and after["height"] == expected_after
                    and (persisted_candidate if expected_decision[0] else before == after)
                )
                row.update(
                    measurement_status="measured",
                    decision=decision,
                    requests=len(traces),
                    response_counts=response_counts,
                    ordered_prompt_prefix=ordered_prompt_prefix,
                    all_completion_path=all_completion_path,
                    request_trace_sha256=sha256_bytes(
                        json.dumps(traces, sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ),
                    after=after,
                    persisted_candidate=persisted_candidate,
                    state_transition_ok=state_transition_ok,
                    expected_decision=expected_decision,
                    expected_requests=expected_requests,
                    expected_before_height=expected_before,
                    expected_after_height=expected_after,
                    oracle_matched=(
                        decision == expected_decision
                        and len(traces) == expected_requests
                        and response_counts == ({"lookup_answer": 100} if expected_requests else {})
                        and ordered_prompt_prefix
                        and all_completion_path
                        and state_transition_ok
                    ),
                )
            except Exception as exc:
                row.update(
                    measurement_status="error",
                    error={"type": type(exc).__name__, "message": str(exc)},
                    requests=len(http_traces) - trace_start,
                    oracle_matched=False,
                )
            report["ledger_rows"].append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
            return row

        chain = Ledger(str(ledgers_dir / "chain"))
        baseline = make_block()
        baseline_row = append_cell("ledger_baseline_genesis", chain, baseline)
        replay_row = append_cell("ledger_exact_block_replay", chain, baseline)
        reused = make_block(height=1, prev=baseline.block_hash(), proof_record=baseline.records[1])
        reused_row = append_cell("ledger_reuse_proof_next_height", chain, reused)
        wrong_prev = make_block(height=2, prev=GENESIS_PREV, proof_record=baseline.records[1])
        append_cell("ledger_wrong_prev_at_expected_height", chain, wrong_prev)

        artifact_block = make_block({"artifact_hash": bytes(32)})
        artifact_row = append_cell(
            "ledger_signed_artifact_mismatch",
            Ledger(str(ledgers_dir / "artifact_mismatch")),
            artifact_block,
        )
        model_id_block = make_block({"base_model_id": "uncommitted-model"})
        model_id_row = append_cell(
            "ledger_signed_model_id_mismatch",
            Ledger(str(ledgers_dir / "model_id_mismatch")),
            model_id_block,
        )
        append_cell(
            "ledger_unsigned_proof_tamper",
            Ledger(str(ledgers_dir / "unsigned_tamper")),
            make_block({"base_model_id": "uncommitted-model"}, resign_proof=False),
        )

        hub_key = base.KeyPair.from_seed(base.sha256(b"P011 local peer hub public test key"))
        hub = InformationHub(node_id="local-peer-hub", keypair=hub_key, pool=AIPool())
        peer_server = AsyncNodeServer("127.0.0.1", 0, hub.handle_packet)
        await peer_server.start()
        require(peer_server._server is not None, "peer server did not start")
        sockets = peer_server._server.sockets or []
        require(len(sockets) == 1, "peer server did not expose exactly one socket")
        peer_port = int(sockets[0].getsockname()[1])
        report["peer_binding"] = {"host": "127.0.0.1", "port": peer_port}

        async def peer_cell(name: str, packet: Packet) -> dict[str, object]:
            before_items = await hub.pool.list_all()
            raw_request = packet.to_bytes()
            (packets_dir / f"{name}.request.packet").write_bytes(raw_request)
            row: dict[str, object] = {
                "name": name,
                "boundary": "AsyncNodeServer TCP -> InformationHub.handle_packet",
                "measurement_status": "started",
                "request_sha256": sha256_bytes(raw_request),
                "pool_count_before": len(before_items),
            }
            try:
                response = await send_packet_expect_one_response("127.0.0.1", peer_port, packet)
                raw_response = response.to_bytes()
                (packets_dir / f"{name}.response.packet").write_bytes(raw_response)
                after_items = await hub.pool.list_all()
                expected_type, expected_ok, expected_before, expected_after, expected_items, error_text = (
                    peer_oracles[name]
                )
                observed_items = response.payload.get("items")
                item_count = len(observed_items) if isinstance(observed_items, list) else None
                error_matches = error_text is None or error_text in str(response.payload.get("error", ""))
                ok_matches = expected_ok is None or response.payload.get("ok") is expected_ok
                row.update(
                    measurement_status="measured",
                    response_sha256=sha256_bytes(raw_response),
                    response_type=response.ptype.value,
                    response_ok=response.payload.get("ok"),
                    response_item_count=item_count,
                    pool_count_after=len(after_items),
                    error_text=response.payload.get("error"),
                    expected_response_type=expected_type,
                    expected_ok=expected_ok,
                    expected_pool_before=expected_before,
                    expected_pool_after=expected_after,
                    expected_item_count=expected_items,
                    oracle_matched=(
                        response.ptype.value == expected_type
                        and ok_matches
                        and len(before_items) == expected_before
                        and len(after_items) == expected_after
                        and (expected_items is None or item_count == expected_items)
                        and error_matches
                    ),
                )
            except Exception as exc:
                row.update(
                    measurement_status="error",
                    error={"type": type(exc).__name__, "message": str(exc)},
                    oracle_matched=False,
                )
            report["peer_rows"].append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
            return row

        model_payload = {
            "model_id": "peer-committed-model",
            "artifact_hash_hex": plan["model"]["sha256"],
            "storage_ref": "local://peer-committed-model",
        }
        proof_payload = {
            "proof_id_hex": base.sha256(b"P011 peer proof").hex(),
            "base_model_id": "peer-uncommitted-model",
            "provider": "llama.cpp",
            "endpoint": endpoint,
            "evalset_hash_hex": plan["evalset"]["sha256"],
            "decode_cfg_hash_hex": base.pdl.DecodeConfig().hash().hex(),
            "claimed_score_scaled": 10000,
            "score_scale": 10000,
            "artifact_hash_hex": bytes(32).hex(),
            "artifact_ref": "local://peer-uncommitted-model",
        }
        await peer_cell(
            "tcp_model_submission",
            Packet(PacketType.NEW_MODEL_RECORD, "local-client", model_payload, ts=base.TS, request_id="model"),
        )
        await peer_cell(
            "tcp_mismatched_proof_submission",
            Packet(PacketType.NEW_PROOF_RECORD, "local-client", proof_payload, ts=base.TS, request_id="proof"),
        )
        malformed_payload = dict(proof_payload)
        malformed_payload.pop("artifact_hash_hex")
        await peer_cell(
            "tcp_malformed_proof",
            Packet(PacketType.NEW_PROOF_RECORD, "local-client", malformed_payload, ts=base.TS, request_id="bad-proof"),
        )
        await peer_cell(
            "tcp_pool_sync",
            Packet(PacketType.POOL_SYNC_REQUEST, "local-client", {}, ts=base.TS, request_id="sync"),
        )

        pool_before_build = await hub.pool.list_all()
        peer_records = await hub.build_records_for_block(limit=100)
        pool_after_build = await hub.pool.list_all()
        require(len(peer_records) == 2, "expected exactly two peer-created records")
        model_records = [record for record in peer_records if int(record.lane) == int(Lane.MODEL)]
        proof_records = [record for record in peer_records if int(record.lane) == int(Lane.PROOF)]
        require(len(model_records) == 1 and len(proof_records) == 1, "peer records have unexpected lanes")
        peer_model = unpack(model_records[0].payload)
        peer_proof = unpack(proof_records[0].payload)
        peer_relationships = {
            "pool_count_before_build": len(pool_before_build),
            "pool_count_after_build": len(pool_after_build),
            "both_records_individually_validate": all(
                validate_record(record) == (True, "ok") for record in peer_records
            ),
            "model_id_disagrees": peer_model["model_id"] != peer_proof["base_model_id"],
            "artifact_hash_disagrees": peer_model["artifact_hash"] != peer_proof["artifact_hash"],
        }
        peer_relationships["all_checks_true"] = (
            peer_relationships["pool_count_before_build"] == 2
            and peer_relationships["pool_count_after_build"] == 0
            and all(
                value is True
                for key_name, value in peer_relationships.items()
                if key_name not in {"pool_count_before_build", "pool_count_after_build", "all_checks_true"}
            )
        )
        report["peer_record_relationships"] = peer_relationships

        peer_block = sign_records(peer_records, 0, GENESIS_PREV)
        peer_ledger = Ledger(str(ledgers_dir / "peer_records"))
        peer_ledger_before_announce = ledger_state(peer_ledger)
        await peer_cell(
            "tcp_block_announce",
            Packet(
                PacketType.BLOCK_ANNOUNCE,
                "local-client",
                {"block_hex": peer_block.to_bytes().hex()},
                ts=base.TS,
                request_id="block-announce",
            ),
        )
        peer_ledger_after_announce = ledger_state(peer_ledger)
        report["block_announce_boundary"] = {
            "implemented_handler": False,
            "ledger_state_before": peer_ledger_before_announce,
            "ledger_state_after": peer_ledger_after_announce,
            "ledger_unchanged": peer_ledger_before_announce == peer_ledger_after_announce,
        }
        peer_append_row = append_cell("peer_records_ledger_append", peer_ledger, peer_block)

        model_payload_baseline = unpack(baseline.records[0].payload)
        artifact_payload = unpack(artifact_block.records[1].payload)
        model_id_payload = unpack(model_id_block.records[1].payload)
        report["ledger_relationship_checks"] = {
            "artifact_mismatch_is_real": artifact_payload["artifact_hash"]
            != model_payload_baseline["artifact_hash"],
            "model_id_mismatch_is_real": model_id_payload["base_model_id"]
            != model_payload_baseline["model_id"],
            "mismatch_records_individually_validate": all(
                validate_record(record) == (True, "ok")
                for record in artifact_block.records + model_id_block.records
            ),
            "replayed_block_bytes_identical": replay_row["candidate_block_sha256"]
            == baseline_row["candidate_block_sha256"],
            "reused_proof_record_identical": reused_row["proof_record_sha256"]
            == baseline_row["proof_record_sha256"],
            "artifact_mismatch_persisted": artifact_row.get("persisted_candidate") is True,
            "model_id_mismatch_persisted": model_id_row.get("persisted_candidate") is True,
            "peer_mismatch_persisted": peer_append_row.get("persisted_candidate") is True,
        }
        report["ledger_relationship_checks"]["all_checks_true"] = all(
            value is True
            for key_name, value in report["ledger_relationship_checks"].items()
            if key_name != "all_checks_true"
        )

        ledger_rows = report["ledger_rows"]
        peer_rows = report["peer_rows"]
        all_measured = (
            len(ledger_rows) == 8
            and len(peer_rows) == 5
            and all(row["measurement_status"] == "measured" for row in ledger_rows + peer_rows)
        )
        all_oracles = all_measured and all(row["oracle_matched"] for row in ledger_rows + peer_rows)
        relationships_ok = (
            report["ledger_relationship_checks"]["all_checks_true"]
            and report["peer_record_relationships"]["all_checks_true"]
            and report["block_announce_boundary"]["ledger_unchanged"]
        )
        report["execution_status"] = "completed" if all_measured else "failed"
        report["oracle_status"] = "all_matched" if all_oracles else "one_or_more_mismatched"
        if all_measured and all_oracles and relationships_ok:
            report["status"] = "ok"
        elif all_measured and relationships_ok:
            report["status"] = "completed_with_oracle_mismatch"
        else:
            report["status"] = "failed"
    except BaseException as exc:
        operational_error = exc
        report["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        report["execution_status"] = report["status"]
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if peer_server is not None:
            try:
                await peer_server.stop()
                report["peer_server_stopped"] = True
            except Exception as exc:
                report["status"] = "failed"
                report["peer_cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}
        if http_server is not None:
            http_server.shutdown()
            http_server.server_close()
        if http_thread is not None:
            http_thread.join(timeout=5)
            report["http_server_stopped"] = not http_thread.is_alive()
            if http_thread.is_alive():
                report["status"] = "failed"
        base.save(output / "http_requests.json", http_traces)
        report["http_request_log_sha256"] = base.digest(output / "http_requests.json")
        report["http_request_count"] = len(http_traces)

        if fixture_owned:
            try:
                require(base.EVAL_PATH.resolve().is_relative_to(base.ROOT.resolve()), "fixture escaped worktree")
                report["eval_fixture_final_sha256"] = base.digest(base.EVAL_PATH)
                require(
                    report["eval_fixture_final_sha256"] == plan["evalset"]["sha256"],
                    "owned eval fixture changed unexpectedly",
                )
                base.EVAL_PATH.unlink()
                report["eval_fixture_removed"] = not base.EVAL_PATH.exists()
                require(report["eval_fixture_removed"], "eval fixture still exists")
            except Exception as exc:
                report["status"] = "failed"
                report["fixture_cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}

        try:
            source_after = source_hashes()
            report["source_hashes_before"] = source_before
            report["source_hashes_after"] = source_after
            report["source_integrity_ok"] = source_before == source_after
            report["tracked_worktree_clean_after"] = not base.git(
                "status", "--porcelain", "--untracked-files=no"
            )
            require(report["source_integrity_ok"], "source hashes changed during run")
            require(report["tracked_worktree_clean_after"], "tracked worktree dirty after run")
        except Exception as exc:
            report["status"] = "failed"
            report["post_integrity_error"] = {"type": type(exc).__name__, "message": str(exc)}
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        base.save(output / "report.json", report)

    if operational_error is not None:
        return 130 if isinstance(operational_error, KeyboardInterrupt) else 1
    return 0 if report.get("status") in {"ok", "completed_with_oracle_mismatch"} else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    return asyncio.run(run_experiment(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

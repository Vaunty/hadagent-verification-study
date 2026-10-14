"""Two-phase honest-model baseline; local cached assets only.

The parent process never calls the target evaluator. Claim scoring and block
validation run in bounded child processes so either can be killed at its frozen
phase deadline.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import replace
import hashlib
import http.client
import inspect
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "hadagent/src")]
from experiments.local_redteam import run as p010
from podl_chain import block as block_module, pdl
from podl_chain.block import Block, BlockHeader
from podl_chain.crypto import KeyPair, sha256
from podl_chain.records import Lane, ModelType, ProofType, Record, pack, unpack

EVAL_PATH = ROOT / "hadagent/data/evalset/evalset.jsonl"
LOCAL_ROOT = ROOT / "experiments/honest_baseline/local"
PROXY = Path(__file__).with_name("answer_blind_proxy.py")
TS = 1791691200


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path | str) -> str:
    return p010.digest(path)


def save(path: Path, value: object) -> None:
    p010.save(path, value)


def load_plan(path: Path) -> tuple[dict, dict]:
    plan = json.loads(path.read_text(encoding="utf-8-sig"))
    require(plan["base_commit"] == "069f6cce89e75bad32b8e969f7e3fe85dae6194e", "wrong base")
    limits = plan["limits"]
    require(
        limits == {
            "startup_s": 120,
            "proxy_startup_s": 30,
            "upstream_request_s": 115,
            "target_request_s": 120,
            "phase_s": 1800,
            "global_s": 3900,
            "shutdown_s": 15,
            "cleanup_reserve_s": 100,
            "max_requests_per_phase": 100,
            "max_total_requests": 200,
            "min_available_ram_bytes": 3221225472,
            "min_output_free_bytes": 209715200,
        },
        "limits differ from preregistration",
    )
    asset_path = (ROOT / plan["asset_plan"]["path"]).resolve()
    require(asset_path.is_relative_to(ROOT.resolve()), "asset plan escaped worktree")
    require(digest(asset_path) == plan["asset_plan"]["sha256"], "asset plan hash mismatch")
    assets = json.loads(asset_path.read_text(encoding="utf-8-sig"))
    expected = plan["asset_identity"]
    require(assets["model"]["sha256"] == expected["model_sha256"], "model pin differs")
    require(assets["evalset"]["sha256"] == expected["evalset_sha256"], "eval pin differs")
    require(assets["runtime"]["binary_sha256"] == expected["runtime_binary_sha256"], "runtime pin differs")
    require(assets["runtime"]["version_output_sha256"] == expected["version_output_sha256"], "version pin differs")
    return plan, assets


def source_hashes(plan_path: Path) -> dict[str, str]:
    plan_path = plan_path.resolve()
    require(plan_path.is_relative_to(ROOT.resolve()), "plan path escaped worktree")
    files = list((ROOT / "hadagent/src/podl_chain").glob("*.py"))
    files += [
        ROOT / "experiments/local_redteam/run.py",
        ROOT / "experiments/local_redteam/participant.py",
        Path(__file__),
        PROXY,
        plan_path,
    ]
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(files)}


def available_ram() -> int:
    if os.name != "nt":
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))

    class Status(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = Status()
    status.dwLength = ctypes.sizeof(Status)
    require(bool(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))), "RAM query failed")
    return int(status.ullAvailPhys)


def existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        require(current.parent != current, "no existing output ancestor")
        current = current.parent
    return current


def preflight(plan_path: Path, expected_commit: str, output: Path | None = None,
              progress: dict | None = None) -> dict:
    plan, assets = load_plan(plan_path)
    result = progress if progress is not None else {}
    result["commit"] = p010.git("rev-parse", "HEAD")
    result["expected_commit"] = expected_commit
    require(result["commit"] == expected_commit, "HEAD differs from reviewed expected commit")
    require(not p010.git("status", "--porcelain"), "tracked worktree must be clean")
    result["tracked_worktree_clean"] = True
    require(not EVAL_PATH.exists(), "eval fixture already exists")
    result["eval_fixture_absent"] = True
    checked = p010.integrity(assets)
    result["asset_count"] = len(checked)
    result["asset_hashes"] = checked
    runtime = assets["runtime"]
    version = subprocess.run(
        [runtime["binary"], "--version"],
        cwd=Path(runtime["binary"]).parent,
        env=p010.child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    version_hash = hashlib.sha256(version.stdout.strip().encode()).hexdigest()
    result["runtime_version_output"] = version.stdout
    result["runtime_version_sha256"] = version_hash
    require(version.returncode == 0 and version_hash == runtime["version_output_sha256"], "runtime version differs")
    ram = available_ram()
    free = shutil.disk_usage(existing_ancestor(output or LOCAL_ROOT)).free
    result["available_ram_bytes"] = ram
    result["required_available_ram_bytes"] = plan["limits"]["min_available_ram_bytes"]
    result["output_free_bytes"] = free
    result["required_output_free_bytes"] = plan["limits"]["min_output_free_bytes"]
    require(ram >= plan["limits"]["min_available_ram_bytes"], "available RAM below frozen gate")
    require(free >= plan["limits"]["min_output_free_bytes"], "output disk below frozen gate")
    require(Path(inspect.getsourcefile(pdl)).resolve() == ROOT / "hadagent/src/podl_chain/pdl.py", "wrong pdl import")
    require(Path(inspect.getsourcefile(Block)).resolve() == ROOT / "hadagent/src/podl_chain/block.py", "wrong block import")
    result.update(platform=platform.platform(), python=sys.version, status="ok")
    return result


def choose_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_llama(process: subprocess.Popen, port: int, deadline: float) -> None:
    startup_deadline = min(deadline, time.monotonic() + 120)
    while time.monotonic() < startup_deadline:
        require(process.poll() is None, "llama-server exited during startup")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            if response.status == 200 and json.loads(response.read()).get("status") == "ok":
                return
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        finally:
            connection.close()
        time.sleep(0.2)
    raise TimeoutError("llama-server startup deadline exceeded")


def wait_proxy(process: subprocess.Popen, ready: Path, deadline: float) -> int:
    end = min(deadline, time.monotonic() + 30)
    while time.monotonic() < end:
        require(process.poll() is None, "proxy exited before ready")
        if ready.exists():
            try:
                value = json.loads(ready.read_text(encoding="utf-8"))
                require(value["host"] == "127.0.0.1", "proxy bound outside loopback")
                return int(value["port"])
            except json.JSONDecodeError:
                pass
        time.sleep(0.1)
    raise TimeoutError("proxy startup deadline exceeded")


def runtime_command(assets: dict, port: int) -> list[str]:
    runtime = assets["runtime"]
    return [
        runtime["binary"], "--model", assets["model"]["path"], "--host", "127.0.0.1",
        "--port", str(port), "--threads", "4", "--threads-batch", "4",
        "--batch-size", "512", "--ubatch-size", "128", "--n-gpu-layers", "0",
        "--ctx-size", "4096", "--parallel", "1", "--seed", "42",
    ]


def make_block(endpoint: str, model_sha: str, eval_sha: str, claim: int) -> bytes:
    key = KeyPair.from_seed(sha256(b"honest signed-block baseline public test key"))
    model_id = "Qwen2.5-1.5B-Instruct-Q4_K_M"
    artifact_ref = "local://honest-baseline-qwen-gguf"
    model = {
        "model_id": model_id,
        "artifact_hash": bytes.fromhex(model_sha),
        "owner_pk": key.pubkey_bytes(),
        "storage_ref": artifact_ref,
        "ts": TS,
    }
    model["sig"] = key.sign(pack(model))
    proof = {
        "proof_id": sha256(b"honest baseline truthful claim"),
        "miner_pk": key.pubkey_bytes(),
        "base_model_id": model_id,
        "provider": "llama.cpp",
        "endpoint": endpoint,
        "evalset_hash": bytes.fromhex(eval_sha),
        "decode_cfg_hash": pdl.DecodeConfig().hash(),
        "claimed_score_scaled": claim,
        "score_scale": 10000,
        "artifact_hash": bytes.fromhex(model_sha),
        "artifact_ref": artifact_ref,
        "ts": TS,
    }
    proof["sig"] = key.sign(pack(proof))
    records = [
        Record(Lane.MODEL, ModelType.MODEL_COMMIT, 1, pack(model)),
        Record(Lane.PROOF, ProofType.PODL_LLM_EVAL, 1, pack(proof)),
    ]
    roots = Block.compute_lane_roots(records)
    header = BlockHeader(1, 0, bytes(32), *roots, TS, key.pubkey_bytes(), b"")
    header = replace(header, sig=key.sign(header.signing_bytes()))
    return Block(header, records).to_bytes()


def expected_request_hashes(pairs: list[tuple[str, str]]) -> list[str]:
    cfg = {"temperature": 0.0, "top_k": 1, "top_p": 1.0, "n_predict": 64}
    return [
        hashlib.sha256(json.dumps({"prompt": prompt, **cfg}).encode("utf-8")).hexdigest()
        for prompt, _answer in pairs
    ]


def audit_proxy(phase: Path, pairs: list[tuple[str, str]], phase_elapsed_s: float) -> dict:
    events_path = phase / "proxy.events.jsonl"
    rows: list[dict] = []
    issues: list[str] = []
    if events_path.exists():
        for line_number, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError("event is not an object")
                rows.append(value)
            except Exception as exc:
                issues.append(f"event line {line_number}: {type(exc).__name__}: {exc}")
    else:
        issues.append("proxy event file absent")
    if len(rows) > 100:
        issues.append("proxy exceeded request cap")
    if [row.get("ordinal") for row in rows] != list(range(len(rows))):
        issues.append("proxy ordinals differ")
    expected_hashes = expected_request_hashes(pairs)
    attempted_requests = len(rows)
    completed_requests = 0
    successful_requests = 0
    outputs: list[str] = []
    raw_hashes: list[str] = []
    for index, row in enumerate(rows):
        try:
            request = (phase / "proxy.raw" / row["request_file"]).read_bytes()
            response = (phase / "proxy.raw" / row["response_file"]).read_bytes()
            request_hash = hashlib.sha256(request).hexdigest()
            response_hash = hashlib.sha256(response).hexdigest()
            if request_hash != row.get("request_body_sha256"):
                raise ValueError("request evidence differs")
            if response_hash != row.get("response_body_sha256"):
                raise ValueError("response evidence differs")
            completed_requests += 1
            raw_hashes.append(response_hash)
            if index >= len(expected_hashes) or request_hash != expected_hashes[index]:
                raise ValueError("request body/order differs")
            if row.get("status") != "ok" or row.get("upstream_http_status") != 200:
                raise ValueError("proxy request failed")
            successful_requests += 1
            value = json.loads(response.decode("utf-8"))
            output = str(value.get("content") or value.get("completion") or "")
            outputs.append(output)
        except Exception as exc:
            issues.append(f"event {index}: {type(exc).__name__}: {exc}")
    normalized_outputs = [pdl.normalize_answer(output) for output in outputs]
    normalized_answers = [pdl.normalize_answer(answer) for _prompt, answer in pairs[:len(outputs)]]
    prefix_by_item = [
        output.startswith(answer)
        for output, answer in zip(normalized_outputs, normalized_answers)
    ]
    prefix = sum(prefix_by_item)
    audit = {
        "requests": len(rows),
        "attempted_requests": attempted_requests,
        "completed_requests": completed_requests,
        "successful_http_200_requests": successful_requests,
        "parsed_generation_responses": len(outputs),
        "complete": len(rows) == completed_requests == successful_requests == len(pairs) == 100 and not issues,
        "issues": issues,
        "events_sha256": digest(events_path) if events_path.exists() else None,
        "request_body_sha256": [row.get("request_body_sha256") for row in rows],
        "response_body_sha256": raw_hashes,
        "generated_text": outputs,
        "normalized_generated_text": normalized_outputs,
        "generated_text_sha256": [hashlib.sha256(output.encode("utf-8")).hexdigest() for output in outputs],
        "prefix_match_by_item": prefix_by_item,
        "prefix_matches": prefix,
        "format_compliant": sum(output.strip() in {"A", "B", "C", "D"} for output in outputs),
        "phase_elapsed_s": phase_elapsed_s,
    }
    save(phase / "proxy.audit.json", audit)
    return audit


def worker(args: argparse.Namespace) -> int:
    row: dict[str, object] = {"status": "failed", "mode": args.mode}
    try:
        require(block_module.verify_podl_llm_eval is pdl.verify_podl_llm_eval, "block verifier import changed")
        parsed = urlsplit(args.endpoint)
        require(
            parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port
            and parsed.path == "/completion" and not parsed.query and not parsed.fragment
            and not parsed.username and not parsed.password,
            "worker endpoint is not owned loopback",
        )
        pairs = pdl.parse_evalset_jsonl(pdl.load_evalset_bytes(str(EVAL_PATH)))
        if args.mode == "score":
            correct = pdl.score_exact_match(args.endpoint, pairs, pdl.DecodeConfig())
            row.update(correct=correct, total=len(pairs), scaled=(correct * 10000) // max(1, len(pairs)))
        else:
            raw = args.block.read_bytes()
            actual_hash = hashlib.sha256(raw).hexdigest()
            require(actual_hash == args.block_sha256, "candidate bytes changed before validation")
            block = Block.from_bytes(raw)
            proof_endpoints = [
                unpack(record.payload).get("endpoint")
                for record in block.records
                if record.lane == Lane.PROOF and record.rtype == ProofType.PODL_LLM_EVAL
            ]
            require(proof_endpoints and all(value == args.endpoint for value in proof_endpoints),
                    "signed proof endpoint differs from owned CLI endpoint")
            for value in proof_endpoints:
                proof_url = urlsplit(value)
                require(
                    proof_url.scheme == "http" and proof_url.hostname == "127.0.0.1"
                    and proof_url.port and proof_url.path == "/completion"
                    and not proof_url.query and not proof_url.fragment
                    and not proof_url.username and not proof_url.password,
                    "signed proof endpoint is not bare owned loopback",
                )
            result = block.validate(bytes(32), 0)
            row.update(decision=list(result), input_block_sha256=actual_hash)
        row["status"] = "ok"
    except Exception as exc:
        row["error"] = {"type": type(exc).__name__, "message": str(exc)}
    save(args.result, row)
    return 0 if row["status"] == "ok" else 1


def freeze_candidate(folder: Path, endpoint: str, assets: dict, claim: int) -> dict:
    path = folder / "frozen_signed_block.msgpack"
    raw = make_block(endpoint, assets["model"]["sha256"], assets["evalset"]["sha256"], claim)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    candidate = {
        "path": str(path),
        "block_sha256": hashlib.sha256(raw).hexdigest(),
        "claimed_score_scaled": claim,
        "endpoint": endpoint,
        "serialized_before_validation_phase": True,
    }
    save(folder / "frozen_candidate.json", candidate)
    return candidate


def run_phase(name: str, folder: Path, plan: dict, assets: dict, global_deadline: float,
              proxy_port: int, candidate: dict | None = None) -> tuple[dict, dict]:
    phase_started = time.monotonic()
    phase = folder / name
    phase.mkdir()
    reserve = plan["limits"]["cleanup_reserve_s"]
    phase_deadline = min(
        global_deadline - reserve,
        phase_started + plan["limits"]["phase_s"] - reserve,
    )
    require(phase_deadline > time.monotonic(), f"{name} has no execution budget after cleanup reserve")
    server_port = choose_port()
    while server_port == proxy_port:
        server_port = choose_port()
    command = runtime_command(assets, server_port)
    env = p010.child_env()
    result: dict = {}
    phase_error: BaseException | None = None
    proxy_command: list[str] = []
    try:
        with p010.owned(command, phase, "llama", env) as model:
            wait_llama(model, server_port, phase_deadline)
            proxy_ready = phase / "proxy.ready.json"
            proxy_command = [
                sys.executable, "-B", "-X", "utf8", str(PROXY),
                "--upstream-port", str(server_port), "--listen-port", str(proxy_port),
                "--ready", str(proxy_ready), "--events", str(phase / "proxy.events.jsonl"),
                "--raw-dir", str(phase / "proxy.raw"), "--max-requests", "100",
                "--upstream-timeout", "115",
            ]
            with p010.owned(proxy_command, phase, "proxy", env) as proxy:
                observed_proxy_port = wait_proxy(proxy, proxy_ready, phase_deadline)
                require(observed_proxy_port == proxy_port, "proxy did not bind frozen port")
                endpoint = f"http://127.0.0.1:{proxy_port}/completion"
                if name == "claim":
                    worker_command = [
                        sys.executable, "-B", "-X", "utf8", str(Path(__file__)), "worker",
                        "--mode", "score", "--endpoint", endpoint,
                        "--result", str(phase / "worker.result.json"),
                    ]
                else:
                    require(candidate is not None, "validation requires a frozen candidate")
                    require(candidate["endpoint"] == endpoint, "frozen candidate endpoint differs")
                    worker_command = [
                        sys.executable, "-B", "-X", "utf8", str(Path(__file__)), "worker",
                        "--mode", "validate", "--endpoint", endpoint,
                        "--block", candidate["path"], "--block-sha256", candidate["block_sha256"],
                        "--result", str(phase / "worker.result.json"),
                    ]
                with p010.owned(worker_command, phase, "worker", env) as process:
                    remaining = phase_deadline - time.monotonic()
                    require(remaining > 0, f"{name} phase deadline elapsed before worker")
                    try:
                        process.wait(timeout=remaining)
                    except subprocess.TimeoutExpired as exc:
                        save(phase / "timeout.json", {
                            "phase": name,
                            "phase_limit_s": plan["limits"]["phase_s"],
                            "cleanup_reserve_s": reserve,
                        })
                        raise TimeoutError(f"{name} worker exceeded execution deadline") from exc
                result = json.loads((phase / "worker.result.json").read_text(encoding="utf-8"))
                require(process.returncode == 0 and result["status"] == "ok", f"{name} worker failed")
    except (Exception, KeyboardInterrupt) as exc:
        phase_error = exc
    pairs = pdl.parse_evalset_jsonl(Path(assets["evalset"]["path"]).read_bytes())
    audit = audit_proxy(phase, pairs, time.monotonic() - phase_started)
    if phase_error is None:
        try:
            require(audit["complete"], f"{name} did not produce complete 100-item trace")
            if name == "claim":
                require(result["correct"] == audit["prefix_matches"],
                        "claim scorer differs from proxy recount")
        except Exception as exc:
            phase_error = exc
    phase_meta = {
        "name": name, "phase_limit_s": plan["limits"]["phase_s"],
        "cleanup_reserve_s": reserve,
        "llama_command": command,
        "proxy_command": proxy_command,
        "model_pid": json.loads((phase / "llama.process.json").read_text())["pid"]
            if (phase / "llama.process.json").exists() else None,
        "proxy_pid": json.loads((phase / "proxy.process.json").read_text())["pid"]
            if (phase / "proxy.process.json").exists() else None,
        "elapsed_s": audit["phase_elapsed_s"],
        "status": "failed" if phase_error else "ok",
        "error": ({"type": type(phase_error).__name__, "message": str(phase_error)}
                  if phase_error else None),
    }
    save(phase / "phase.json", phase_meta)
    if phase_error is not None:
        raise phase_error
    return result, audit


def execute_two_phase(output: Path, plan: dict, assets: dict, global_deadline: float) -> dict:
    require(
        time.monotonic() < global_deadline - plan["limits"]["cleanup_reserve_s"],
        "global execution deadline elapsed before claim",
    )
    proxy_port = choose_port()
    endpoint = f"http://127.0.0.1:{proxy_port}/completion"
    claim_result, claim_audit = run_phase(
        "claim", output, plan, assets, global_deadline, proxy_port,
    )
    claim = int(claim_result["scaled"])
    save(output / "truthful_claim.json", {
        "prefix_matches": claim_result["correct"], "total": claim_result["total"],
        "claimed_score_scaled": claim, "score_scale": 10000,
        "frozen_before_validation": True,
    })
    candidate = freeze_candidate(output, endpoint, assets, claim)
    require(
        time.monotonic() < global_deadline - plan["limits"]["cleanup_reserve_s"],
        "global execution deadline elapsed before validation",
    )
    validation_result, validation_audit = run_phase(
        "validation", output, plan, assets, global_deadline, proxy_port, candidate,
    )
    require(
        validation_result["input_block_sha256"] == candidate["block_sha256"]
        and digest(candidate["path"]) == candidate["block_sha256"],
        "frozen candidate changed during validation",
    )
    total_requests = claim_audit["requests"] + validation_audit["requests"]
    require(total_requests <= plan["limits"]["max_total_requests"], "global request cap exceeded")
    validation_scaled = (validation_audit["prefix_matches"] * 10000) // 100
    if validation_scaled != claim:
        expected = [False, f"PoDL failed: claimed score mismatch (computed {validation_scaled})"]
    elif validation_scaled < 8000:
        expected = [False, f"PoDL failed: score below target ({validation_scaled} < 8000)"]
    else:
        expected = [True, "ok"]
    request_sequences_equal = claim_audit["request_body_sha256"] == validation_audit["request_body_sha256"]
    require(request_sequences_equal, "phase request bodies/order differ")
    claim_command = json.loads((output / "claim/phase.json").read_text(encoding="utf-8"))["llama_command"]
    validation_command = json.loads((output / "validation/phase.json").read_text(encoding="utf-8"))["llama_command"]
    claim_command[claim_command.index("--port") + 1] = "<owned-port>"
    validation_command[validation_command.index("--port") + 1] = "<owned-port>"
    same_model_server_configuration = claim_command == validation_command
    require(same_model_server_configuration, "model-server flags differ between phases")
    generated_equal = [
        left == right for left, right in zip(
            claim_audit["generated_text"], validation_audit["generated_text"]
        )
    ]
    raw_equal = [
        left == right for left, right in zip(
            claim_audit["response_body_sha256"], validation_audit["response_body_sha256"]
        )
    ]
    normalized_equal = [
        left == right for left, right in zip(
            claim_audit["normalized_generated_text"], validation_audit["normalized_generated_text"]
        )
    ]
    prefix_equal = [
        left == right for left, right in zip(
            claim_audit["prefix_match_by_item"], validation_audit["prefix_match_by_item"]
        )
    ]
    prefix_transitions = {
        "both_correct": sum(left and right for left, right in zip(
            claim_audit["prefix_match_by_item"], validation_audit["prefix_match_by_item"]
        )),
        "claim_only_correct": sum(left and not right for left, right in zip(
            claim_audit["prefix_match_by_item"], validation_audit["prefix_match_by_item"]
        )),
        "validation_only_correct": sum(not left and right for left, right in zip(
            claim_audit["prefix_match_by_item"], validation_audit["prefix_match_by_item"]
        )),
        "both_incorrect": sum(not left and not right for left, right in zip(
            claim_audit["prefix_match_by_item"], validation_audit["prefix_match_by_item"]
        )),
    }
    metrics = {
        "claim": {
            "correct_under_normalized_prefix_scorer": claim_audit["prefix_matches"],
            "total": 100,
            "one_letter_compliant": claim_audit["format_compliant"],
            "claimed_score_scaled": claim,
            "score_arithmetic": {
                "correct_count": claim_audit["prefix_matches"],
                "weighted_numerator": claim_audit["prefix_matches"] * 10000,
                "scale": 10000,
                "divisor": 100, "quotient": claim,
                "remainder": (claim_audit["prefix_matches"] * 10000) % 100,
            },
            "attempted_requests": claim_audit["attempted_requests"],
            "completed_requests": claim_audit["completed_requests"],
            "successful_http_200_requests": claim_audit["successful_http_200_requests"],
            "phase_elapsed_s": claim_audit["phase_elapsed_s"],
        },
        "validation": {
            "correct_under_normalized_prefix_scorer": validation_audit["prefix_matches"],
            "total": 100,
            "one_letter_compliant": validation_audit["format_compliant"],
            "recomputed_score_scaled": validation_scaled,
            "score_arithmetic": {
                "correct_count": validation_audit["prefix_matches"],
                "weighted_numerator": validation_audit["prefix_matches"] * 10000,
                "scale": 10000,
                "divisor": 100, "quotient": validation_scaled,
                "remainder": (validation_audit["prefix_matches"] * 10000) % 100,
            },
            "attempted_requests": validation_audit["attempted_requests"],
            "completed_requests": validation_audit["completed_requests"],
            "successful_http_200_requests": validation_audit["successful_http_200_requests"],
            "phase_elapsed_s": validation_audit["phase_elapsed_s"],
            "decision": validation_result["decision"][0],
            "reason": validation_result["decision"][1],
        },
        "claimed_minus_recomputed_scaled": claim - validation_scaled,
        "paired_exact_text_agreement": sum(generated_equal),
        "paired_normalized_text_agreement": sum(normalized_equal),
        "paired_prefix_outcome_agreement": sum(prefix_equal),
        "paired_normalized_text_difference_indices": [
            i for i, equal in enumerate(normalized_equal) if not equal
        ],
        "paired_prefix_outcome_difference_indices": [
            i for i, equal in enumerate(prefix_equal) if not equal
        ],
        "prefix_outcome_transitions": prefix_transitions,
        "paired_total": 100,
    }
    return {
        "status": "ok" if validation_result["decision"] == expected else "completed_with_mismatch",
        "claim_phase": claim_result,
        "validation_phase": validation_result,
        "frozen_candidate": candidate,
        "expected_validation_decision": expected,
        "decision_matches_predicate": validation_result["decision"] == expected,
        "total_model_requests": total_requests,
        "ordered_request_bodies_equal": request_sequences_equal,
        "same_proxy_port_both_phases": True,
        "same_model_server_configuration": same_model_server_configuration,
        "metrics": metrics,
        "generated_text_equal_count": sum(generated_equal),
        "generated_text_difference_indices": [i for i, equal in enumerate(generated_equal) if not equal],
        "raw_response_body_equal_count": sum(raw_equal),
        "raw_response_body_difference_indices": [i for i, equal in enumerate(raw_equal) if not equal],
        "claim_format_compliant": claim_audit["format_compliant"],
        "validation_format_compliant": validation_audit["format_compliant"],
    }


def main_run(args: argparse.Namespace) -> int:
    plan_path = args.plan.resolve()
    require(plan_path.is_relative_to(ROOT.resolve()), "plan path escaped worktree")
    plan, assets = load_plan(plan_path)
    output = args.output.resolve()
    require(output.is_relative_to(LOCAL_ROOT.resolve()), "output must stay under ignored honest-baseline local dir")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    global_deadline = started + plan["limits"]["global_s"]
    report: dict[str, object] = {
        "status": "running", "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "plan_sha256": digest(plan_path), "commit": p010.git("rev-parse", "HEAD"),
        "expected_commit": args.expected_commit,
    }
    save(output / "started.json", report)
    created_eval = False
    before: dict[str, str] | None = None
    try:
        before = source_hashes(plan_path)
        save(output / "source_hashes_before.json", before)
        report["preflight"] = {}
        preflight(plan_path, args.expected_commit, output, report["preflight"])
        EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        handle = EVAL_PATH.open("xb")
        created_eval = True
        with handle:
            handle.write(Path(assets["evalset"]["path"]).read_bytes())
        require(digest(EVAL_PATH) == assets["evalset"]["sha256"], "eval fixture copy differs")

        report.update(execute_two_phase(output, plan, assets, global_deadline))
    except (Exception, KeyboardInterrupt) as exc:
        report["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if created_eval:
            try:
                report["eval_fixture_final_sha256"] = digest(EVAL_PATH)
                require(report["eval_fixture_final_sha256"] == assets["evalset"]["sha256"],
                        "owned eval fixture changed")
                EVAL_PATH.unlink()
                report["eval_fixture_removed"] = True
            except Exception as exc:
                report["status"] = "failed"
                report["cleanup_error"] = {"type": type(exc).__name__, "message": str(exc)}
        try:
            after = source_hashes(plan_path)
            save(output / "source_hashes_after.json", after)
            tracked_clean = not p010.git("status", "--porcelain")
            if before is None:
                report["post_integrity"] = {
                    "status": "not_compared",
                    "reason": "source hashes before execution were unavailable",
                    "tracked_worktree_clean": tracked_clean,
                }
            else:
                require(before == after, "source hashes changed")
                require(tracked_clean, "tracked worktree dirty after run")
                report["post_integrity"] = "ok"
        except Exception as exc:
            report["status"] = "failed"
            report["post_integrity"] = {"type": type(exc).__name__, "message": str(exc)}
        report["elapsed_s"] = time.monotonic() - started
        report["global_limit_s"] = plan["limits"]["global_s"]
        report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save(output / "report.json", report)
    return 0 if report["status"] == "ok" else 1


def preflight_command(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    require(output.is_relative_to(LOCAL_ROOT.resolve()), "preflight output must stay local")
    output.mkdir(parents=True, exist_ok=False)
    value: dict[str, object] = {}
    try:
        plan_path = args.plan.resolve()
        require(plan_path.is_relative_to(ROOT.resolve()), "plan path escaped worktree")
        value["plan_sha256"] = digest(plan_path)
        preflight(plan_path, args.expected_commit, output, value)
        value["status"] = "ok"
    except (Exception, KeyboardInterrupt) as exc:
        value["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        value["error"] = {"type": type(exc).__name__, "message": str(exc)}
    value["checked_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save(output / ("preflight.json" if value["status"] == "ok" else "preflight.failure.json"), value)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0 if value["status"] == "ok" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("preflight")
    check.add_argument("--plan", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    check.add_argument("--expected-commit", required=True)
    run = sub.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--execute-model", action="store_true")
    run.add_argument("--expected-commit", required=True)
    internal = sub.add_parser("worker")
    internal.add_argument("--mode", choices=["score", "validate"], required=True)
    internal.add_argument("--endpoint", required=True)
    internal.add_argument("--block", type=Path)
    internal.add_argument("--block-sha256")
    internal.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "worker":
        return worker(args)
    if args.command == "preflight":
        return preflight_command(args)
    require(args.execute_model, "model execution requires explicit --execute-model")
    return main_run(args)


if __name__ == "__main__":
    raise SystemExit(main())

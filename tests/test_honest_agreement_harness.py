"""P-005 preparation only: synthetic files, fake processes, and intercepted HTTP.

All experiment rows are SIMULATED. Pytest outcomes measure harness correctness,
not model agreement. These tests never launch a binary, bind a socket, or fetch.
"""

from copy import deepcopy
import io
import json
import subprocess
import threading
import urllib.error

import pytest

from podl_chain import pdl
from experiments.honest_agreement import analyze, run


class FakeProcess:
    def __init__(self, world, command, **kwargs):
        self.world = world
        self.index = len(world.processes)
        self.case = world.cases[self.index]
        self.pid = 1000 + self.index
        self.active = not self.case.get("exit_early", False)
        self.terminated = self.killed = False
        self.items = 0
        self.command = command
        self.options = kwargs
        world.processes.append(self)
        world.current = self

    def poll(self):
        return None if self.active else 0

    def terminate(self):
        self.terminated = True
        if not self.case.get("needs_kill"):
            self.active = False

    def kill(self):
        if self.case.get("kill_fails"):
            raise OSError("SIMULATED kill failure")
        self.killed = True
        self.active = False

    def wait(self, timeout):
        if self.active:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return 0


class FakeWorld:
    def __init__(self):
        self.cases = [{"outputs": ["A", "X"]} for _ in range(6)]
        self.processes = []
        self.current = None
        self.requests = []

    def open(self, request, timeout):
        if isinstance(request, str):
            assert request == "http://127.0.0.1:18080/health"
            return io.BytesIO(b'{"status":"ok"}')
        process = self.current
        assert request.full_url == "http://127.0.0.1:18080/completion"
        body = json.loads(request.data)
        index = process.items % 2
        assert body == {"prompt": f"synthetic question {index}", "temperature": 0.0,
                        "top_k": 1, "top_p": 1.0, "n_predict": 64}
        assert 0 < timeout <= 10
        self.requests.append(body)
        error = process.case.get("error")
        if error and index == process.case.get("error_at", 0):
            raise error
        process.items += 1
        return io.BytesIO(json.dumps({"content": process.case["outputs"][index]}).encode())


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    model = tmp_path / "synthetic.gguf"
    binary = tmp_path / "fake-server.exe"
    evalset = tmp_path / "synthetic.jsonl"
    model.write_bytes(b"SIMULATED model bytes; never executed")
    binary.write_bytes(b"SIMULATED binary bytes; never executed")
    runtime = tmp_path / "fake-runtime.dll"
    runtime.write_bytes(b"SIMULATED DLL bytes; never loaded")
    evalset.write_text("\n".join(json.dumps({"prompt": f"synthetic question {i}", "answer": a})
                                  for i, a in enumerate(("A", "B"))) + "\n", encoding="utf-8")
    plan = {
        "schema_version": 1, "repeats": 3, "expected_items": 2,
        "mode": "reexecution", "preregistered_reference_correct": 1,
        "reference_run_id": "reference/repeat-0", "context_size": 512, "seed": 0,
        "hardware": {"scope": "consumer CPU/iGPU", **{k: "SIMULATED" for k in ("cpu", "gpu", "driver", "ram", "os")}},
        "startup_timeout_s": 5, "request_timeout_s": 10,
        "run_timeout_s": 30, "shutdown_timeout_s": 1, "experiment_timeout_s": 300,
        "model": {"path": str(model), "sha256": run.digest(model.read_bytes())},
        "evalset": {"path": str(evalset), "sha256": run.digest(evalset.read_bytes()),
                    "source": "in-test synthetic fixture", "license": "test fixture",
                    "selection": "all synthetic rows in file order", "prompt_template": "synthetic question {i}"},
        "configurations": [
            {"id": name, "binary": str(binary), "binary_sha256": run.digest(binary.read_bytes()),
             "version": "SIMULATED-version", "backend": "cpu", "threads": threads,
             "batch": 16, "ubatch": 8, "gpu_layers": 0, "parallel": 1, "load_workers": 0,
             "runtime_files_sha256": {runtime.name: run.digest(runtime.read_bytes())},
             "release_asset_sha256": run.digest(b"SIMULATED archive digest"),
             "version_output_sha256": run.digest(b"SIMULATED-version output")}
            for name, threads in (("reference", 1), ("candidate", 4))
        ],
    }
    world = FakeWorld()
    monkeypatch.setattr(run.subprocess, "Popen", lambda command, **kw: FakeProcess(world, command, **kw))
    monkeypatch.setattr(run, "read_version", lambda path: "SIMULATED-version output")
    monkeypatch.setattr(run, "code_commit", lambda: "a" * 40)
    monkeypatch.setattr(run, "choose_port", lambda: 18080)
    monkeypatch.setattr(run.urllib.request, "build_opener", lambda *handlers: world)
    return plan, world, tmp_path / "runs.jsonl"


def execute(prepared):
    plan, _, output = prepared
    return run.run_experiment(plan, output, approval_note="GREEN in-test stubs only",
                              evidence_label="SIMULATED")


def test_real_scorer_single_generation_and_analysis(prepared, monkeypatch):
    plan, world, output = prepared
    world.cases[1]["outputs"] = ["A with a harmless suffix", "X"]
    world.cases[2]["outputs"] = ["X", "X"]
    world.cases[5]["outputs"] = ["X", "X"]
    original_score = pdl.score_exact_match
    calls = []

    def score_spy(*args):
        calls.append(args)
        return original_score(*args)

    monkeypatch.setattr(pdl, "score_exact_match", score_spy)
    completion_before, urlopen_before = pdl.llama_cpp_completion, pdl.urllib.request.urlopen
    rows = execute(prepared)
    assert len(calls) == 6
    assert len(world.requests) == 12  # One generation per item, not capture + re-score.
    assert pdl.llama_cpp_completion is completion_before
    assert pdl.urllib.request.urlopen is urlopen_before
    assert rows == [json.loads(line) for line in output.read_text().splitlines()]
    assert all(row["evidence_label"] == "SIMULATED" and row["status"] == "ok" for row in rows)
    assert all(p.terminated and not p.active for p in world.processes)
    for process in world.processes:
        command = process.command
        assert command[command.index("--host") + 1] == "127.0.0.1"
        assert command[command.index("--n-gpu-layers") + 1] == "0"
        assert process.options["shell"] is False
        if run.os.name == "nt":
            assert process.options["creationflags"] == subprocess.CREATE_NO_WINDOW
    report = analyze.analyze_rows(rows, prepared[0])
    assert report["exact_score_equality_rejection_component"] == analyze.fraction(2, 5)
    assert report["per_prompt_agreement_to_reference"][0]["raw_agreement"] == analyze.fraction(2, 5)
    assert report["per_prompt_agreement_to_reference"][1]["raw_agreement"] == analyze.fraction(5, 5)
    within = report["within_config_repeat_stability"]
    assert within["reference"]["score_agreement"] == analyze.fraction(1, 3)
    assert within["reference"]["whole_output_agreement"] == analyze.fraction(0, 3)
    assert within["candidate"]["whole_output_agreement"] == analyze.fraction(1, 3)
    assert report["evidence_label"] == "SIMULATED" and report["complete"] is True
    config_path = output.with_suffix(".config.json")
    config_path.write_text(json.dumps(plan), encoding="utf-8")
    assert analyze.main([str(output), "--config", str(config_path), "--output", str(output.with_suffix(".report.json"))]) == 0
    assert report["per_run_reference_comparisons"][0]["category"] == "different-output/same-score"
    assert rows[0]["code_sources_sha256"] == run.source_hashes()


def test_failed_run_recorded_and_server_stopped(prepared):
    _, world, _ = prepared
    world.cases[3].update(error=TimeoutError("SIMULATED timeout"), error_at=1)
    rows = execute(prepared)
    assert rows[3]["status"] == "failed" and rows[3]["result"] is None
    assert rows[3]["error"]["completed_items"] == 1
    assert not world.processes[3].active
    report = analyze.analyze_rows(rows, prepared[0])
    assert report["exact_score_equality_rejection_component"] == analyze.fraction(0, 4)
    assert len(report["failed_runs"]) == 1 and report["complete"] is False


def test_interrupt_stops_owned_server_and_reports_missing_runs(prepared):
    _, world, _ = prepared
    world.cases[3]["error"] = KeyboardInterrupt()
    rows = execute(prepared)
    assert len(rows) == 4 and rows[-1]["status"] == "interrupted"
    assert all(not process.active for process in world.processes)
    report = analyze.analyze_rows(rows, prepared[0])
    assert report["missing_runs"] == ["candidate/repeat-1", "candidate/repeat-2"]


def test_shutdown_escalates_to_kill(prepared):
    _, world, _ = prepared
    world.cases[0]["needs_kill"] = True
    rows = execute(prepared)
    assert rows[0]["status"] == "ok"
    assert world.processes[0].killed and not world.processes[0].active


def test_failed_cleanup_stops_the_matrix(prepared):
    _, world, _ = prepared
    world.cases[0].update(needs_kill=True, kill_fails=True)
    rows = execute(prepared)
    assert len(rows) == 1 and rows[0]["error"]["type"] == "ServerCleanupError"


def test_early_server_exit_is_a_failed_run(prepared):
    _, world, _ = prepared
    world.cases[0]["exit_early"] = True
    rows = execute(prepared)
    assert rows[0]["status"] == "failed" and rows[0]["error"]["stage"] == "startup"
    with pytest.raises(ValueError, match="reference"):
        analyze.analyze_rows(rows, prepared[0])


def test_hash_mismatch_prevents_any_process(prepared):
    plan, world, output = prepared
    plan["model"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum mismatch"):
        execute(prepared)
    assert not world.processes and not output.exists()


@pytest.mark.parametrize("change", ["modified", "extra"])
def test_runtime_dll_integrity_prevents_process(prepared, change):
    _, world, output = prepared
    path = output.parent / ("fake-runtime.dll" if change == "modified" else "extra.dll")
    path.write_bytes(b"unexpected runtime bytes")
    with pytest.raises(ValueError, match="checksum mismatch|unpinned runtime DLL"):
        execute(prepared)
    assert not world.processes


def test_plan_mode_never_executes(prepared, monkeypatch, capsys):
    plan, world, output = prepared
    path = output.with_suffix(".config.json")
    path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(run, "run_experiment", lambda *a, **k: pytest.fail("plan mode executed"))
    assert run.main(["--config", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "PLAN ONLY"
    assert not world.processes


@pytest.mark.parametrize("url", [
    "http://example.test:18080/completion", "http://localhost:18080/completion",
    "http://127.0.0.1:18081/completion", "https://127.0.0.1:18080/completion",
    "http://user@127.0.0.1:18080/completion", "http://127.0.0.1:18080/elsewhere",
])
def test_transport_refuses_other_destinations(prepared, url):
    _, world, _ = prepared
    transport = run.LoopbackTransport(18080, 10, run.time.monotonic() + 30)
    with pytest.raises(ValueError, match="loopback"):
        transport.open(url)
    assert not world.requests


def test_transport_disables_proxies_and_redirects(monkeypatch):
    handlers = []
    monkeypatch.setattr(run.urllib.request, "build_opener", lambda *h: handlers.extend(h))
    run.LoopbackTransport(18080, 10, 100)
    assert isinstance(handlers[0], run.urllib.request.ProxyHandler)
    assert handlers[0].proxies == {}
    with pytest.raises(RuntimeError, match="redirect"):
        handlers[1].redirect_request(None, None, 302, "", {}, "http://example.test/")


@pytest.mark.parametrize("mutation", ["duplicate", "model", "label", "prompts", "score", "missing_reference"])
def test_analyzer_refuses_incomparable_or_corrupt_data(prepared, mutation):
    rows = deepcopy(execute(prepared))
    if mutation == "duplicate":
        rows.append(rows[0])
    elif mutation == "model":
        rows[1]["artifacts"]["model_sha256"] = "0" * 64
    elif mutation == "label":
        rows[1]["evidence_label"] = "MEASURED"
    elif mutation == "prompts":
        rows[1]["result"]["outputs"][0]["prompt_sha256"] = "0" * 64
    elif mutation == "score":
        rows[1]["result"]["score_scaled"] = 42
    elif mutation == "missing_reference":
        rows = rows[1:]
    with pytest.raises(ValueError):
        analyze.analyze_rows(rows, prepared[0])


def test_no_comparisons_are_undefined_not_perfect(prepared):
    rows = execute(prepared)[:1]
    report = analyze.analyze_rows(rows, prepared[0])
    assert report["exact_score_equality_rejection_component"] == analyze.fraction(0, 0)
    assert report["within_config_repeat_stability"]["reference"]["score_agreement"] == analyze.fraction(0, 0)
    assert len(report["missing_runs"]) == 5


@pytest.mark.parametrize("problem", ["reserved", "duplicate_factors", "mixed_build"])
def test_plan_rejects_ambiguous_configuration_identity(prepared, problem):
    plan, world, _ = prepared
    if problem == "reserved":
        plan["configurations"][1]["id"] = "model"
    elif problem == "duplicate_factors":
        plan["configurations"][1]["threads"] = 1
    else:
        plan["configurations"][1]["binary_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        execute(prepared)
    assert not world.processes


def test_analyzer_requires_actual_original_plan(prepared):
    rows = execute(prepared)[:1]
    rows[0]["planned_run_ids"] = [rows[0]["run_id"]]
    rows[0]["plan_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="original plan"):
        analyze.analyze_rows(rows, prepared[0])


def test_version_pin_mismatch_stops_before_server(prepared, monkeypatch):
    monkeypatch.setattr(run, "read_version", lambda _: "unexpected build")
    rows = execute(prepared)
    assert len(rows) == 1 and not prepared[1].processes
    assert rows[0]["error"]["stage"] == "version"
    assert rows[0]["stop_reason"] == "reference failed"


@pytest.mark.parametrize("outputs", [["A", "B"], ["X", "X"]])
def test_floor_ceiling_reference_stops_without_agreement_claim(prepared, outputs):
    plan, world, _ = prepared
    world.cases[0]["outputs"] = outputs
    rows = execute(prepared)
    assert len(rows) == 1 and len(world.processes) == 1
    report = analyze.analyze_rows(rows, plan)
    assert report["agreement_statistics"] is None
    assert "15..85" in report["stop_reason"]


def test_calibration_disagreement_stops_matrix(prepared):
    prepared[0]["preregistered_reference_correct"] = 0
    rows = execute(prepared)
    assert len(rows) == 1 and "calibration" in rows[0]["stop_reason"]


def test_calibration_only_runs_reference_without_matrix_statistics(prepared):
    plan, world, output = prepared
    plan["preregistered_reference_correct"] = None
    rows = run.run_experiment(plan, output, approval_note="GREEN stubs", evidence_label="SIMULATED", calibration_only=True)
    assert len(rows) == len(world.processes) == 1 and rows[0]["calibration_only"] is True
    report = analyze.analyze_rows(rows, plan)
    assert report["agreement_statistics"] is None and "calibration only" in report["stop_reason"]


def test_health_timeout_stops_owned_process(prepared, monkeypatch):
    def timeout(*args):
        raise TimeoutError("SIMULATED health timeout")
    monkeypatch.setattr(run, "wait_for_health", timeout)
    rows = execute(prepared)
    assert rows[0]["error"]["stage"] == "startup"
    assert prepared[1].processes[0].terminated


def test_budget_prevents_starting_later_runs(prepared, monkeypatch):
    offset = [0]
    monkeypatch.setattr(run.time, "monotonic", lambda: 100 + offset[0])
    original = run.measure_session
    def measured(*args, **kwargs):
        rows = original(*args, **kwargs)
        offset[0] += prepared[0]["experiment_timeout_s"] + 1
        return rows
    monkeypatch.setattr(run, "measure_session", measured)
    rows = execute(prepared)
    assert len(rows) == len(prepared[1].processes) == 1
    assert len(analyze.analyze_rows(rows, prepared[0])["missing_runs"]) == 5


def load_plan(prepared):
    plan = prepared[0]
    plan.update(mode="same_endpoint_load", repeats=1, load_prompt="Benign synthetic background request")
    plan["configurations"] = plan["configurations"][:1]
    plan["configurations"][0].update(parallel=2, load_workers=1)
    plan["reference_run_id"] = "reference/repeat-0/idle"
    return plan


def test_idle_loaded_share_one_process_with_real_background_worker(prepared, monkeypatch):
    plan = load_plan(prepared)
    world = prepared[1]
    opened, release = threading.Event(), threading.Event()
    original = world.open
    def open_with_load(request, timeout):
        if not isinstance(request, str) and json.loads(request.data)["prompt"] == plan["load_prompt"]:
            opened.set()
            assert release.wait(2), "scoring never released synthetic background request"
            return io.BytesIO(b'{"content":"benign background reply"}')
        if not isinstance(request, str) and world.current.items >= 2:
            assert opened.wait(2), "background request never started"
            response = original(request, timeout)
            if world.current.items == 4:
                release.set()
            return response
        return original(request, timeout)
    monkeypatch.setattr(world, "open", open_with_load)
    rows = execute(prepared)
    assert len(world.processes) == 1 and world.processes[0].terminated
    assert [r["config"]["phase"] for r in rows] == ["idle", "loaded"]
    assert all(r["status"] == "ok" for r in rows)
    assert rows[1]["load"]["audit_requests_with_client_overlap"] == 2
    report = analyze.analyze_rows(rows, plan)
    assert report["same_instance_score_mismatch_fraction"] == analyze.fraction(0, 1)
    assert report["same_instance_idle_loaded_comparisons"][0]["reference_run_id"].endswith("/idle")
    rows[1]["server_pid"] += 1
    with pytest.raises(ValueError, match="same server"):
        analyze.analyze_rows(rows, plan)


def test_load_failure_not_counted_as_success(prepared, monkeypatch):
    plan = load_plan(prepared)
    world = prepared[1]
    original = world.open
    def failing_load(request, timeout):
        if not isinstance(request, str) and json.loads(request.data)["prompt"] == plan["load_prompt"]:
            raise TimeoutError("SIMULATED load failure")
        return original(request, timeout)
    monkeypatch.setattr(world, "open", failing_load)
    rows = execute(prepared)
    assert rows[0]["status"] == "ok" and rows[1]["status"] == "failed"
    assert rows[1]["result"] is None and world.processes[0].terminated
    assert analyze.analyze_rows(rows, plan)["same_instance_score_mismatch_fraction"] == analyze.fraction(0, 0)


def test_deadline_watchdog_kills_stalled_server(prepared, monkeypatch):
    world = prepared[1]
    process = FakeProcess(world, ["SIMULATED"])
    class ImmediateTimer:
        def __init__(self, delay, callback):
            self.callback = callback
        def start(self):
            self.callback()
        def cancel(self):
            pass
        def join(self, timeout):
            pass
        def is_alive(self):
            return False
    monkeypatch.setattr(run.threading, "Timer", ImmediateTimer)
    with pytest.raises(TimeoutError, match="deadline"):
        with run.server_deadline(process, 0, 1):
            assert process.killed and not process.active

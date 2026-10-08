"""Synthetic budget and return-copy checks; no downloads, binaries or model runs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

DESKTOP = Path(__file__).resolve().parents[1] / 'experiments/honest_agreement/desktop'


@pytest.fixture
def control(monkeypatch):
    monkeypatch.syspath_prepend(str(DESKTOP))
    spec = importlib.util.spec_from_file_location('desktop_control_under_test', DESKTOP / 'control.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_deadline_charges_pilot_and_refuses_retry(control, tmp_path):
    study = control.reserve_stage(tmp_path, 'laptop', 'q4', 'calibration', now=1000)
    assert study['deadline_utc'] == pytest.approx(1000 + 21600 - 600.0312538)
    with pytest.raises(FileExistsError):
        control.reserve_stage(tmp_path, 'laptop', 'q4', 'calibration', now=1010)
    next_stage = control.reserve_stage(tmp_path, 'laptop', 'q4', 'matrix', now=3000)
    assert next_stage == study
    with pytest.raises(TimeoutError, match='does not fit'):
        control.reserve_stage(tmp_path, 'laptop', 'load', 'matrix', now=study['deadline_utc'] - 3629)
    assert not (tmp_path / 'state/load.matrix.started.json').exists()


def test_ledger_cannot_begin_with_candidate_or_switch_machine(control, tmp_path):
    with pytest.raises(ValueError, match='begin with'):
        control.reserve_stage(tmp_path, 'desktop', 'fp16', 'calibration', now=100)
    study = control.reserve_stage(tmp_path, 'desktop', 'q4', 'calibration', now=100)
    assert study['deadline_utc'] == 28900
    with pytest.raises(ValueError, match='mix machines'):
        control.reserve_stage(tmp_path, 'laptop', 'q4', 'matrix', now=100)


def test_authorization_requires_recorded_gates_and_bom_json(control, tmp_path):
    (tmp_path / 'state').mkdir()
    a = {'p005b_record': 'SIMULATED quorum', 'offline_bundle_review_record': 'SIMULATED review'}
    p = tmp_path / 'state/authorization.json'
    p.write_text(json.dumps(a), encoding='utf-8-sig')
    assert control.authorization(tmp_path, 'laptop') == 'P-005b'
    with pytest.raises(ValueError, match='specifications'):
        control.authorization(tmp_path, 'desktop')
    a.update(desktop_specs_confirmed=True, p008_record='SIMULATED approval',
             matthew_out_of_band_record='UNRESOLVED', runtime_review_record='SIMULATED review')
    p.write_text(json.dumps(a), encoding='utf-8-sig')
    with pytest.raises(ValueError, match='matthew_out_of_band'):
        control.authorization(tmp_path, 'desktop')


def test_return_copy_relativizes_only_known_root_and_rejects_other_paths(control, tmp_path):
    original = {'command': [str(tmp_path / 'tools/server.exe'), '--host', '127.0.0.1'],
                'result': {'correct': 21}, 'server_log': str(tmp_path / 'results/server.log')}
    before = deepcopy(original)
    copied = control.safe_return(original, tmp_path)
    assert original == before
    assert copied['result'] == original['result']
    assert copied['server_log'] == 'results/server.log'
    with pytest.raises(ValueError, match='private path'):
        control.safe_return({'error': 'C:\\Users\\someone\\private-file'}, tmp_path)
    with pytest.raises(ValueError, match='private path'):
        control.safe_return({'error': '/home/someone/private-file'}, tmp_path)


def test_plan_cuts_and_cross_machine_frozen_settings():
    from experiments.honest_agreement.build_desktop_bundle import make_plans, RETAIN
    base = json.loads((DESKTOP.parent / 'plan.example.json').read_text(encoding='utf-8'))
    base['model']['filename'] = 'qwen2.5-1.5b-instruct-q4_k_m.gguf'
    plans = make_plans(base)
    laptop, desktop = plans['laptop-q4'], plans['desktop-q4']
    assert tuple(c['id'] for c in laptop['configurations']) == RETAIN
    assert desktop['configurations'][:6] == laptop['configurations']
    assert laptop['repeats'] == desktop['repeats'] == 1
    assert laptop['run_timeout_s'] == desktop['run_timeout_s'] == 1800
    assert laptop['reference_run_id'] == base['reference_run_id']
    assert laptop['reference_score_gate'] == base['reference_score_gate']
    for key in ('seed', 'context_size', 'expected_items'):
        assert laptop[key] == desktop[key] == base[key]
    assert len(desktop['configurations']) == 9
    assert plans['desktop-fp16']['model']['sha256'] != desktop['model']['sha256']
    assert plans['desktop-load']['mode'] == 'same_endpoint_load'
    assert plans['desktop-load']['run_timeout_s'] == 3600
    assert plans['laptop-load']['configurations'][0]['threads'] == 8


def test_preflight_failure_has_single_use_record_and_summary(control, tmp_path, monkeypatch):
    from experiments.honest_agreement import run
    (tmp_path / 'state').mkdir()
    control.save(tmp_path / 'state/authorization.json', {
        'p005b_record': 'SIMULATED approved', 'offline_bundle_review_record': 'SIMULATED checked'})
    control.save(tmp_path / 'state/q4.calibration.plan.json', {'fixture': 'SIMULATED'})
    for key in list(control.os.environ):
        if key.startswith(('LLAMA_', 'GGML_')) or key.endswith('VISIBLE_DEVICES'):
            monkeypatch.delenv(key)
    def fail(*args, **kwargs):
        raise ValueError('SIMULATED artifact preflight failure')
    monkeypatch.setattr(run, 'run_experiment', fail)
    result = control.execute(tmp_path, 'laptop', 'q4', 'calibration')
    assert result['status'] == 'failed_or_incomplete'
    assert result['error_type'] == 'ValueError'
    assert (tmp_path / 'state/q4.calibration.started.json').exists()
    assert (tmp_path / 'results/q4.calibration.finished.json').exists()
    with pytest.raises(FileExistsError):
        control.execute(tmp_path, 'laptop', 'q4', 'calibration')


def test_export_rejects_mismatched_plan_even_for_failed_reference(control, tmp_path):
    (tmp_path / 'results').mkdir()
    (tmp_path / 'verify_bundle.py').write_text('# SIMULATED verifier bytes, not executed\n')
    control.save(tmp_path / 'state/study.json', {'fixture': 'SIMULATED'})
    control.save(tmp_path / 'state/q4.calibration.plan.json', {'fixture': 'SIMULATED'})
    (tmp_path / 'results/q4.calibration.jsonl').write_text(json.dumps({
        'status': 'failed', 'plan_sha256': 'f' * 64}) + '\n')
    with pytest.raises(ValueError, match='including failed rows'):
        control.export_results(tmp_path)


def test_export_keeps_failure_markers_excludes_raw_logs(control, tmp_path):
    from experiments.honest_agreement import analyze, run
    (tmp_path / 'results/private-logs').mkdir(parents=True)
    (tmp_path / 'results/private-logs/server.log').write_text('SIMULATED private local path')
    (tmp_path / 'verify_bundle.py').write_text('# SIMULATED verifier bytes, not executed\n')
    control.save(tmp_path / 'state/study.json', {'fixture': 'SIMULATED'})
    control.save(tmp_path / 'state/q4.calibration.started.json', {'fixture': 'SIMULATED attempt'})
    plan = {'fixture': 'SIMULATED'}
    control.save(tmp_path / 'state/q4.calibration.plan.json', plan)
    raw = json.dumps({'status': 'failed', 'plan_sha256': run.digest(analyze.canonical(plan).encode()),
                      'command': [str(tmp_path / 'tools/server.exe')]}) + '\n'
    (tmp_path / 'results/q4.calibration.jsonl').write_text(raw)
    result = control.export_results(tmp_path)
    assert result['raw_logs_included'] is False
    assert (tmp_path / 'return/package/state/q4.calibration.started.json').exists()
    assert not (tmp_path / 'return/package/results/private-logs').exists()
    assert (tmp_path / 'results/q4.calibration.jsonl').read_text() == raw
    assert control.read(tmp_path / 'return/package/bundle-manifest.json')['allowed_mutable_roots'] == []


def test_fresh_process_cannot_reset_deadline_or_double_charge_pilot(control, tmp_path):
    study = control.reserve_stage(tmp_path, 'laptop', 'q4', 'calibration', now=1000)
    program = """import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import control
root=Path(sys.argv[2])
before=control.read(root/'state/study.json')
try:
    control.reserve_stage(root,'laptop','q4','matrix',now=before['deadline_utc']-10979)
except TimeoutError:
    print(json.dumps(control.read(root/'state/study.json')))
else:
    raise SystemExit('stage improperly started without cleanup reserve')
"""
    result = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(DESKTOP), str(tmp_path)],
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == study
    assert not (tmp_path / 'state/q4.matrix.started.json').exists()


def test_final_analysis_write_overrun_is_recorded_and_cannot_start_next_stage(control, tmp_path, monkeypatch):
    from experiments.honest_agreement import run, analyze
    (tmp_path / 'state').mkdir()
    control.save(tmp_path / 'state/authorization.json', {
        'p005b_record': 'SIMULATED approved', 'offline_bundle_review_record': 'SIMULATED checked'})
    control.save(tmp_path / 'state/q4.calibration.plan.json', {'fixture': 'SIMULATED'})
    for key in list(control.os.environ):
        if key.startswith(('LLAMA_', 'GGML_')) or key.endswith('VISIBLE_DEVICES'):
            monkeypatch.delenv(key)
    now = [1000.0]
    monkeypatch.setattr(control.time, 'time', lambda: now[0])
    calls = []
    def synthetic_runner(*args, **kwargs):
        calls.append(kwargs)
        return [{'status': 'ok', 'stop_reason': 'calibration only; SIMULATED'}]
    monkeypatch.setattr(run, 'run_experiment', synthetic_runner)
    monkeypatch.setattr(analyze, 'analyze_rows', lambda *args: {'fixture': 'SIMULATED report'})
    original_save = control.save
    def slow_final_write(path, data):
        original_save(path, data)
        if path.name.endswith('.analysis.json'):
            now[0] = control.read(tmp_path / 'state/study.json')['deadline_utc'] + 5
    monkeypatch.setattr(control, 'save', slow_final_write)
    control.execute(tmp_path, 'laptop', 'q4', 'calibration')
    assert control.read(tmp_path / 'results/q4.calibration.finished.json')['budget_overrun_seconds'] == 5
    with pytest.raises(TimeoutError):
        control.reserve_stage(tmp_path, 'laptop', 'q4', 'matrix')
    assert len(calls) == 1


def test_runtime_pin_never_defaults_to_a_self_measured_digest(tmp_path):
    from experiments.honest_agreement.build_desktop_bundle import python_runtime_pin
    pin = python_runtime_pin()
    assert pin['sha256'].startswith('UNRESOLVED')
    path = tmp_path / 'runtime-pin.json'
    pin.update(sha256='a' * 64, digest_source='https://unapproved.example/checksum')
    path.write_text(json.dumps(pin))
    with pytest.raises(ValueError, match='official python.org'):
        python_runtime_pin(path)
    pin['digest_source'] = 'https://www.python.org/TEST-FIXTURE-NOT-A-REAL-DIGEST'
    path.write_text(json.dumps(pin))
    assert python_runtime_pin(path) == pin
    pin['version'] = '3.15.0'
    path.write_text(json.dumps(pin))
    with pytest.raises(ValueError, match='fixed'):
        python_runtime_pin(path)

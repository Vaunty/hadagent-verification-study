"""Single-use study stages and portable return copies. No downloader."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import zipfile

from verify_bundle import verify


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def authorization(root, machine):
    a = read(root / 'state/authorization.json')
    keys = ['p005b_record', 'offline_bundle_review_record']
    if machine == 'desktop':
        keys += ['p008_record', 'matthew_out_of_band_record', 'runtime_review_record']
        if a.get('desktop_specs_confirmed') is not True:
            raise ValueError('desktop specifications must be recorded before approval')
    for key in keys:
        if not isinstance(a.get(key), str) or not a[key].strip() or 'UNRESOLVED' in a[key].upper():
            raise ValueError('missing recorded prerequisite: ' + key)
    # This is a guard against accidental execution, not a source of human authority.
    return 'P-005b' if machine == 'laptop' else 'P-008 + P-005b (see private authorization record)'


def freeze(root, machine):
    from experiments.honest_agreement import run
    authorization(root, machine)
    if sys.version_info[:3] != (3, 14, 4) or sys.maxsize <= 2**32:
        raise ValueError('use the reviewed CPython 3.14.4 AMD64 portable runtime')
    hardware = read(root / 'state/hardware.json')
    if any(not isinstance(hardware.get(k), str) or not hardware[k].strip()
           or hardware[k].lower() == 'unavailable' for k in ('cpu', 'gpu', 'driver', 'ram', 'os')):
        raise ValueError('complete read-only hardware inventory is required')
    if machine == 'desktop' and 'RTX 3060' not in hardware['gpu']:
        raise ValueError('desktop GPU differs from the P-008 RTX 3060 scope')
    builds = read(root / 'state/builds.json')
    # inspect emits a list of verified build identities; no score enters these plans.
    builds = builds['builds'] if isinstance(builds, dict) else builds
    mapping = {(b['version'], b['backend']): b for b in builds}
    if len(mapping) != len(builds):
        raise ValueError('duplicate inspected build identities')
    for condition in (('q4', 'fp16', 'load') if machine == 'desktop' else ('q4', 'load')):
        plan = read(root / f'plans/{machine}-{condition}.template.json')
        plan['hardware'] = {'scope': plan['hardware']['scope'], **{
            k: hardware[k] for k in ('cpu', 'gpu', 'driver', 'ram', 'os')}}
        plan['amendment'] = 'P-005b' if machine == 'laptop' else 'P-008 + P-005b'
        for c in plan['configurations']:
            b = mapping[(c['version'], c['backend'])]
            for key in ('binary', 'binary_sha256', 'runtime_files_sha256',
                        'release_asset_sha256', 'version_output_sha256'):
                c[key] = b[key]
            if machine == 'desktop' and c['backend'] != 'cpu':
                c['device'] = b['device']
            # Paths are relative so return copies preserve the canonical plan hash.
            candidate = Path(c['binary'])
            if candidate.is_absolute() or '..' in candidate.parts:
                raise ValueError('build binary path must be bundle-relative')
            run.checked_artifact(root / candidate, c['binary_sha256'])
            run.checked_runtime(c, root / candidate)
        for key in ('model', 'evalset'):
            run.checked_artifact(root / plan[key]['path'], plan[key]['sha256'])
        run.validate_plan(plan)
        if 'UNRESOLVED' in run.canonical(plan).upper():
            raise ValueError('a plan still contains unresolved metadata')
        # Separate calibration under the same scientific settings, even for a two-phase plan.
        calibration = deepcopy(plan)
        calibration['run_timeout_s'] = 1800
        save(root / f'state/{condition}.calibration.plan.json', calibration)
        save(root / f'state/{condition}.matrix.template.json', plan)
    return {'status': 'plans frozen', 'machine': machine, 'inference_started': False}


def stage_allocation(machine, condition, phase):
    if phase == 'calibration':
        return 1830
    if condition == 'load':
        return 3630
    return (9 if machine == 'desktop' else 6) * 1830 if condition == 'q4' else 1830


def reserve_stage(root, machine, condition, phase, now=None):
    now = time.time() if now is None else now
    state = root / 'state'
    ledger = state / 'study.json'
    if not ledger.exists():
        if (condition, phase) != ('q4', 'calibration'):
            raise ValueError('study must begin with the Q4 reference calibration')
        charged = 600.0312538 if machine == 'laptop' else 0
        total = 21600 if machine == 'laptop' else 28800
        save(ledger, {'machine': machine, 'started_utc': now, 'prior_pilot_seconds': charged,
                      'deadline_utc': now + total - charged, 'total_budget_seconds': total})
    study = read(ledger)
    if study['machine'] != machine:
        raise ValueError('cannot mix machines in a study ledger')
    allocation = stage_allocation(machine, condition, phase)
    if study['deadline_utc'] - now < allocation:
        raise TimeoutError('full stage allocation does not fit; record budget-missing, never reset the ledger')
    marker = state / f'{condition}.{phase}.started.json'
    save(marker, {'started_utc': now, 'allocation_seconds': allocation,
                  'deadline_utc': study['deadline_utc']})
    return study


def execute(root, machine, condition, phase):
    from experiments.honest_agreement import run, analyze
    note = authorization(root, machine)
    if any(k.startswith(('LLAMA_', 'GGML_')) or k in ('CUDA_VISIBLE_DEVICES', 'HIP_VISIBLE_DEVICES',
                                                     'ROCR_VISIBLE_DEVICES') for k in os.environ):
        raise ValueError('ambient model/backend override variables are present; stop before inference')
    if condition == 'fp16' and machine != 'desktop':
        raise ValueError('FP16 is outside the laptop amendment')
    if condition != 'q4':
        q4 = read(root / 'results/q4.matrix.summary.json')
        if q4['status'] != 'complete':
            raise ValueError('secondary conditions wait for the complete Q4 matrix')
    if condition == 'load' and machine == 'desktop':
        if read(root / 'results/fp16.matrix.summary.json')['status'] != 'complete':
            raise ValueError('load condition is last, after FP16')
    plan_path = root / f'state/{condition}.{phase}.plan.json'
    if phase == 'matrix' and not plan_path.exists():
        calibration_plan = read(root / f'state/{condition}.calibration.plan.json')
        rows = [json.loads(s) for s in (root / f'results/{condition}.calibration.jsonl').read_text(encoding='utf-8').splitlines()]
        analyze.analyze_rows(rows, calibration_plan)
        if (len(rows) != 1 or rows[0]['status'] != 'ok'
                or not rows[0]['stop_reason'].startswith('calibration only;')):
            raise ValueError('calibration gate failed; study stops, no replacement')
        plan = read(root / f'state/{condition}.matrix.template.json')
        plan['preregistered_reference_correct'] = rows[0]['result']['correct']
        plan['calibration_provenance'] = {
            'jsonl': f'results/{condition}.calibration.jsonl',
            'sha256': sha(root / f'results/{condition}.calibration.jsonl')}
        save(plan_path, plan)
    plan = read(plan_path)
    study = reserve_stage(root, machine, condition, phase)
    output = root / f'results/{condition}.{phase}.jsonl'
    output.parent.mkdir(exist_ok=True)
    try:
        rows = run.run_experiment(plan, output, approval_note=note,
            calibration_only=phase == 'calibration',
            external_deadline=time.monotonic() + max(0, study['deadline_utc'] - time.time()))
    except (Exception, KeyboardInterrupt) as error:
        summary = {'status': 'failed_or_incomplete', 'stage': 'runner_invocation',
                   'error_type': type(error).__name__, 'error': str(error), 'no_retry': True}
        save(root / f'results/{condition}.{phase}.summary.json', summary)
        save(root / f'results/{condition}.{phase}.finished.json', {
            'finished_utc': datetime.now(timezone.utc).isoformat(),
            'budget_overrun_seconds': max(0, time.time() - study['deadline_utc'])})
        return summary
    good = (len(rows) == 1 and rows[0]['status'] == 'ok'
            and rows[0]['stop_reason'].startswith('calibration only;')) if phase == 'calibration' else (
        len(rows) == len(run.planned_runs(plan)) and all(r['status'] == 'ok' and not r['stop_reason'] for r in rows))
    summary = {'status': 'complete' if good else 'failed_or_incomplete', 'rows': len(rows),
               'finished_utc': datetime.now(timezone.utc).isoformat(), 'no_retry': True,
               'budget_overrun_seconds': max(0, time.time() - study['deadline_utc'])}
    save(root / f'results/{condition}.{phase}.summary.json', summary)
    try:
        report = analyze.analyze_rows(rows, plan)
    except ValueError as error:
        save(root / f'results/{condition}.{phase}.analysis-error.json', {'error': str(error)})
    else:
        save(root / f'results/{condition}.{phase}.analysis.json', report)
    save(root / f'results/{condition}.{phase}.finished.json', {
        'finished_utc': datetime.now(timezone.utc).isoformat(),
        'budget_overrun_seconds': max(0, time.time() - study['deadline_utc']),
        'measurement_note': 'After scoring, cleanup, analysis and summary writes; excludes this final timestamp write.'})
    return summary


def safe_return(value, root):
    if isinstance(value, dict):
        return {k: safe_return(v, root) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_return(v, root) for v in value]
    if not isinstance(value, str):
        return value
    original = value
    for spelling in (str(root), root.as_posix()):
        value = value.replace(spelling + '\\', '').replace(spelling + '/', '')
    if value != original:
        value = value.replace('\\', '/')
    if re.search(r'(?i)([a-z]:[\\/]|\\\\|/Users/|/home/)', value):
        raise ValueError('return copy contains an absolute/private path; review locally')
    return value


def export_results(root):
    dest = root / 'return/package'
    dest.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(root / 'verify_bundle.py', dest / 'verify_bundle.py')
    # Allowlist analytical evidence; omit raw logs, authorization records and full inventories.
    paths = list((root / 'results').glob('*.json')) + list((root / 'results').glob('*.jsonl'))
    paths += list((root / 'state').glob('*.plan.json'))
    paths += list((root / 'state').glob('*.started.json'))
    paths += [root / 'state/study.json']
    derivations = []
    for p in paths:
        rel = p.relative_to(root)
        q = dest / rel
        if p.suffix == '.jsonl':
            q.parent.mkdir(parents=True, exist_ok=True)
            with q.open('x', encoding='utf-8') as f:
                for line in p.read_text(encoding='utf-8').splitlines():
                    row = safe_return(json.loads(line), root)
                    row['return_copy_note'] = 'Paths relativized; raw logs remain on source machine.'
                    f.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
        else:
            save(q, safe_return(read(p), root))
        derivations.append({'path': rel.as_posix(), 'private_original_sha256': sha(p),
                            'return_copy_sha256': sha(q)})
    save(dest / 'return-provenance.json', {
        'note': 'Raw files stay local; analytical fields unchanged, absolute bundle paths relativized. '
                'Calibration provenance refers to private_original_sha256, not rewritten copies.',
        'files': derivations})
    from experiments.honest_agreement import analyze
    for p in (dest / 'results').glob('*.jsonl'):
        plan = read(dest / 'state' / (p.stem + '.plan.json'))
        rows = [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines()]
        expected_hash = hashlib.sha256(analyze.canonical(plan).encode()).hexdigest()
        if any(row.get('plan_sha256') != expected_hash for row in rows):
            raise ValueError('returned row does not match its frozen plan, including failed rows')
        # Valid references must still analyze with the unchanged canonical plan.
        if rows and rows[0]['status'] == 'ok':
            analyze.analyze_rows(rows, plan)
    files = {p.relative_to(dest).as_posix(): {'sha256': sha(p), 'size': p.stat().st_size}
             for p in sorted(dest.rglob('*')) if p.is_file()}
    save(dest / 'bundle-manifest.json', {'schema_version': 1, 'files': files,
        'allowed_mutable_roots': []})
    anchor = sha(dest / 'bundle-manifest.json')
    verify(dest, dest / 'bundle-manifest.json', anchor)
    archive = root / 'return/results.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(dest.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(dest).as_posix())
    return {'status': 'private return copy prepared; manual privacy review still required',
            'manifest_sha256': anchor, 'zip_sha256': sha(archive),
            'raw_logs_included': False, 'original_raw_files_unchanged': True}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['freeze', 'calibration', 'matrix', 'export'])
    p.add_argument('--machine', choices=['desktop', 'laptop'], default='desktop')
    p.add_argument('--condition', choices=['q4', 'fp16', 'load'], default='q4')
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    p.add_argument('--expected-manifest-sha256', required=True)
    a = p.parse_args(argv)
    root = a.root.resolve()
    verify(root, root / 'bundle-manifest.json', a.expected_manifest_sha256)
    os.chdir(root)
    if a.action == 'freeze':
        result = freeze(root, a.machine)
    elif a.action == 'export':
        result = export_results(root)
    else:
        try:
            result = execute(root, a.machine, a.condition, a.action)
        except TimeoutError as error:
            result = {'status': 'budget_missing', 'reason': str(error),
                      'condition': a.condition, 'phase': a.action, 'no_retry': True}
            save(root / f'results/{a.condition}.{a.action}.budget-missing.json', result)
    print(json.dumps(result, indent=2))
    return 1 if result.get('status') in ('failed_or_incomplete', 'budget_missing') else 0


if __name__ == '__main__':
    raise SystemExit(main())

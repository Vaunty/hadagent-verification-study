"""P010: single-use, preregistered local HTTP adversarial evaluation.

No HadAgent function or network primitive is patched. Run from a clean frozen
worktree; artifacts and all attempts stay local. Not a chain/peer experiment.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import http.client
import inspect
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'hadagent/src')]
from podl_chain import pdl, block as block_module
from podl_chain.block import Block, BlockHeader
from podl_chain.crypto import KeyPair, sha256
from podl_chain.records import Record, Lane, ModelType, ProofType, pack, unpack
from core.podl_verifier import verify_podl_llm_eval_fixed_scale

EVAL_PATH = ROOT / 'hadagent/data/evalset/evalset.jsonl'
TS = 1791691200  # fixed synthetic signing timestamp, not observed execution time


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, obj):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(obj, f, indent=2, sort_keys=True)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def child_env():
    env = os.environ.copy()
    for key in list(env):
        if key.lower() in ('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy', 'pythonoptimize'):
            del env[key]
    env['NO_PROXY'] = '*'
    env['PYTHONPATH'] = str(ROOT / 'hadagent/src') + os.pathsep + str(ROOT)
    env['PYTHONUTF8'] = '1'
    return env


@contextmanager
def owned(command, folder, stem, env):
    with (folder / f'{stem}.process.log').open('xb') as out:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=subprocess.STDOUT, shell=False,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        save(folder / f'{stem}.process.json', {'command': command, 'pid': process.pid})
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
            save(folder / f'{stem}.exit.json', {'exit_code': process.returncode})


def wait_ready(process, path, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('participant exited before ready')
        if path.exists():
            try:
                ready = json.loads(path.read_text(encoding='utf-8'))
                if ready['host'] != '127.0.0.1' or not 1 <= ready['port'] <= 65535:
                    raise ValueError('invalid participant binding')
                return ready['port']
            except json.JSONDecodeError:
                pass  # file may have just been created
        time.sleep(.1)
    raise TimeoutError('participant readiness timeout')


def signed_block(endpoint, model_sha, eval_sha, *, claim=10000, bad_signature=False, bad_eval=False):
    # Public deterministic test-only key; never a real account or credential.
    key = KeyPair.from_seed(sha256(b'P010 public local experiment key'))
    model_id = 'Qwen2.5-1.5B-Instruct-Q4_K_M'
    artifact_ref = 'local://p010-committed-qwen-gguf'
    model = {'model_id': model_id, 'artifact_hash': bytes.fromhex(model_sha),
             'owner_pk': key.pubkey_bytes(), 'storage_ref': artifact_ref, 'ts': TS}
    model['sig'] = key.sign(pack(model))
    proof = {'proof_id': sha256(b'P010 benchmark known to participant'),
             'miner_pk': key.pubkey_bytes(), 'base_model_id': model_id,
             'provider': 'llama.cpp', 'endpoint': endpoint,
             'evalset_hash': bytes(32) if bad_eval else bytes.fromhex(eval_sha),
             'decode_cfg_hash': pdl.DecodeConfig().hash(), 'claimed_score_scaled': claim,
             'score_scale': 10000, 'artifact_hash': bytes.fromhex(model_sha),
             'artifact_ref': artifact_ref, 'ts': TS}
    proof['sig'] = key.sign(pack(proof))
    records = [Record(Lane.MODEL, ModelType.MODEL_COMMIT, 1, pack(model)),
               Record(Lane.PROOF, ProofType.PODL_LLM_EVAL, 1, pack(proof))]
    data_root, model_root, proof_root = Block.compute_lane_roots(records)
    header = BlockHeader(1, 1, bytes(32), data_root, model_root, proof_root, TS, key.pubkey_bytes(), b'')
    header = replace(header, sig=bytes(64) if bad_signature else key.sign(header.signing_bytes()))
    return Block(header, records).to_bytes()


def evaluate_cell(args):
    # Executed in a separate bounded process. Original functions are untouched.
    if block_module.verify_podl_llm_eval is not pdl.verify_podl_llm_eval:
        raise RuntimeError('original block verifier import changed')
    source_file = Path(pdl.__file__).resolve()
    if (source_file != ROOT / 'hadagent/src/podl_chain/pdl.py'
            or Path(block_module.__file__).resolve() != ROOT / 'hadagent/src/podl_chain/block.py'
            or Path(inspect.getsourcefile(verify_podl_llm_eval_fixed_scale)).resolve() != ROOT / 'core/podl_verifier.py'):
        raise RuntimeError('module source does not belong to this worktree')
    url = urlsplit(args.endpoint)
    if not (url.scheme == 'http' and url.hostname == '127.0.0.1' and url.port
            and url.path == '/completion' and not url.query and not url.fragment
            and not url.username and not url.password):
        raise ValueError('only the owned loopback endpoint is allowed')
    start = time.monotonic()
    row = {'status': 'failed', 'cell': args.name, 'kind': args.kind,
           'source_file': str(source_file), 'evidence': 'MEASURED on local processes'}
    try:
        if args.kind == 'reference':
            pairs = pdl.parse_evalset_jsonl(pdl.load_evalset_bytes(str(EVAL_PATH)))
            row['correct'] = pdl.score_exact_match(args.endpoint, pairs, pdl.DecodeConfig())
            row['total'] = len(pairs)
        else:
            raw = Path(args.block).read_bytes()
            block = Block.from_bytes(raw)
            if args.kind == 'block':
                result = block.validate(bytes(32), 1)
            else:
                proof = unpack(block.records[1].payload)
                result = verify_podl_llm_eval_fixed_scale(proof, str(EVAL_PATH), 8000)
            row['decision'] = list(result)
            row['block_sha256'] = hashlib.sha256(raw).hexdigest()
        row['status'] = 'ok'
    except Exception as exc:
        row['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    row['elapsed_s'] = time.monotonic() - start
    save(args.result, row)
    return 0 if row['status'] == 'ok' else 1


def integrity(plan):
    checked = {}
    entries = [(plan['model']['path'], plan['model']['sha256']),
               (plan['evalset']['path'], plan['evalset']['sha256']),
               (plan['runtime']['binary'], plan['runtime']['binary_sha256'])]
    entries += [(str(Path(plan['runtime']['binary']).parent / name), value)
                for name, value in plan['runtime']['runtime_files_sha256'].items()]
    for path, expected in entries:
        actual = digest(path)
        if actual != expected:
            raise ValueError(f'artifact hash mismatch: {path}')
        checked[path] = actual
    base = Path(plan['runtime']['binary']).resolve().parent
    pinned = {(base / name).resolve() for name in plan['runtime']['runtime_files_sha256']}
    dlls = {p.resolve() for p in base.rglob('*') if p.is_file() and p.suffix.lower() == '.dll'}
    if not dlls.issubset(pinned):
        raise ValueError('runtime directory contains an unpinned DLL')
    return checked


def source_hashes():
    files = list((ROOT / 'hadagent/src/podl_chain').glob('*.py'))
    files += [ROOT / 'core/podl_verifier.py', Path(__file__), Path(__file__).with_name('participant.py')]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)}


def request_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def audit_requests(requests, mode, cell):
    rows = request_rows(requests) if requests.exists() else []
    pairs = pdl.parse_evalset_jsonl(EVAL_PATH.read_bytes())
    prefix_ok = (len(rows) <= len(pairs) and
                 [x.get('request', {}).get('prompt') for x in rows] == [p for p, _ in pairs[:len(rows)]])
    audit = {'requests': len(rows), 'expected_items': len(pairs), 'ordered_prompt_prefix': prefix_ok,
             'complete_100_item_trace': len(rows) == 100,
             'all_requests_ok': all(x['status'] == 'ok' for x in rows),
             'requests_sha256': digest(requests) if requests.exists() else None,
             'proxied_to_owned_model_server': mode == 'proxy',
             'completed_responses': sum(x['status'] == 'ok' for x in rows)}
    if mode == 'proxy':
        audit['body_preservation_verified'] = all(
            x['status'] == 'ok' and x.get('upstream_http_status') == 200 and
            x.get('upstream_body_sha256') == x.get('response_sha256') for x in rows)
    if prefix_ok:
        audit['observed_prefix_matches'] = sum(
            x['status'] == 'ok' and pdl.normalize_answer(x['raw_output']).startswith(pdl.normalize_answer(a))
            for x, (_, a) in zip(rows, pairs))
    save(cell / 'request_audit.json', audit)
    return audit


def run_cell(plan, folder, name, mode, kind, claim=10000, bad_signature=False, bad_eval=False, upstream=None):
    cell = folder / name
    cell.mkdir()
    env = child_env()
    ready, requests = cell / 'ready.json', cell / 'requests.jsonl'
    command = [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('participant.py')),
               '--mode', mode, '--evalset', str(EVAL_PATH), '--ready', str(ready), '--log', str(requests)]
    if upstream:
        command += ['--upstream-port', str(upstream)]
    try:
        with owned(command, cell, 'participant', env) as participant:
            port = wait_ready(participant, ready)
            endpoint = f'http://127.0.0.1:{port}/completion'
            raw = signed_block(endpoint, plan['model']['sha256'], plan['evalset']['sha256'],
                               claim=claim, bad_signature=bad_signature, bad_eval=bad_eval)
            block_path = cell / 'signed_block.msgpack'
            block_path.write_bytes(raw)
            result = cell / 'result.json'
            command = [sys.executable, '-X', 'utf8', str(Path(__file__)), 'cell', '--name', name,
                       '--kind', kind, '--endpoint', endpoint, '--block', str(block_path), '--result', str(result)]
            with owned(command, cell, 'verifier', env) as verifier:
                try:
                    verifier.wait(timeout=plan['reference_timeout_s'] if kind == 'reference' else 180)
                except subprocess.TimeoutExpired:
                    save(cell / 'timeout.json', {'status': 'failed', 'reason': 'cell deadline exceeded'})
                    raise
            if not result.exists():
                raise RuntimeError('verifier produced no result')
            row = json.loads(result.read_text(encoding='utf-8'))
    finally:
        audit = audit_requests(requests, mode, cell)
    if not audit['ordered_prompt_prefix'] or not audit['all_requests_ok']:
        raise RuntimeError('audit request sequence or response failed')
    if row['status'] != 'ok':
        raise RuntimeError(f'cell failed: {name}')
    if kind == 'reference':
        if (row['correct'] != audit['observed_prefix_matches'] or audit['requests'] != 100
                or not audit['body_preservation_verified']):
            raise RuntimeError('reference response audit differs from original scorer')
    return row, audit


def main_run(args):
    plan = json.loads(args.plan.read_text(encoding='utf-8-sig'))
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    created_eval = False
    before_sources = None
    report = {'status': 'running', 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'commit': git('rev-parse', 'HEAD'), 'plan_sha256': digest(args.plan),
              'reference_requested': not args.adversarial_only, 'rows': []}
    save(folder / 'started.json', report)
    try:
        if git('status', '--porcelain'):
            raise ValueError('tracked source must be clean before execution')
        save(folder / 'integrity_before.json', integrity(plan))
        before_sources = source_hashes()
        save(folder / 'source_hashes_before.json', before_sources)
        # Keep the version output verbatim and pin the binary independently.
        version = subprocess.run([plan['runtime']['binary'], '--version'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 timeout=30, cwd=Path(plan['runtime']['binary']).parent,
                                 env=child_env(), creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        save(folder / 'runtime_version.json', {'returncode': version.returncode,
             'combined_output': version.stdout,
             'stripped_sha256': hashlib.sha256(version.stdout.strip().encode()).hexdigest()})
        if (version.returncode != 0 or hashlib.sha256(version.stdout.strip().encode()).hexdigest()
                != plan['runtime']['version_output_sha256']):
            raise RuntimeError('pinned runtime version command failed or output differs')
        EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        if EVAL_PATH.exists():
            raise ValueError('eval fixture path already exists; never replace or reuse it')
        with EVAL_PATH.open('xb') as f:
            created_eval = True
            f.write(Path(plan['evalset']['path']).read_bytes())
        if digest(EVAL_PATH) != plan['evalset']['sha256']:
            raise ValueError('copied evalset hash differs')
        expected = [
            ('lookup_original_block', 'lookup', 'block', 10000, False, False, [True, 'ok'], 100),
            ('wrong_answers', 'wrong', 'block', 0, False, False, [False, 'PoDL failed: score below target (0 < 8000)'], 100),
            ('wrong_claim', 'lookup', 'block', 0, False, False, [False, 'PoDL failed: claimed score mismatch (computed 10000)'], 100),
            ('invalid_producer_signature', 'lookup', 'block', 10000, True, False, [False, 'bad producer signature'], 0),
            ('incorrect_eval_hash', 'lookup', 'block', 10000, False, True, [False, 'PoDL failed: evalset hash mismatch'], 0),
            ('lookup_fixed_scale_standalone', 'lookup', 'fixed', 10000, False, False, [True, 'ok'], 100),
        ]
        for name, mode, kind, claim, bad_sig, bad_eval, oracle, count in expected:
            row, audit = run_cell(plan, folder, name, mode, kind, claim, bad_sig, bad_eval)
            passed = row['decision'] == oracle and audit['requests'] == count
            report['rows'].append({'name': name, 'row': row, 'audit': audit, 'oracle_matched': passed})
            print(json.dumps({'cell': name, 'decision': row['decision'], 'requests': audit['requests'], 'oracle_matched': passed}), flush=True)
            if not passed:
                raise AssertionError(f'predeclared oracle did not match: {name}')
        if not args.adversarial_only:
            runtime = plan['runtime']
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
            command = [runtime['binary'], '--model', plan['model']['path'], '--host', '127.0.0.1', '--port', str(port),
                       '--threads', '4', '--threads-batch', '4', '--batch-size', '512', '--ubatch-size', '128',
                       '--n-gpu-layers', '0', '--ctx-size', '4096', '--parallel', '1', '--seed', '42']
            with owned(command, folder, 'llama', child_env()) as llama:
                deadline = time.monotonic() + 120
                ready = False
                while time.monotonic() < deadline:
                    if llama.poll() is not None:
                        raise RuntimeError('llama-server exited during startup')
                    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                    try:
                        conn.request('GET', '/health')
                        response = conn.getresponse()
                        ready = response.status == 200 and json.loads(response.read()).get('status') == 'ok'
                    except (OSError, ValueError):
                        pass
                    finally:
                        conn.close()
                    if ready:
                        break
                    time.sleep(.2)
                if not ready:
                    raise TimeoutError('llama-server readiness timeout')
                if llama.poll() is not None:
                    raise RuntimeError('owned llama-server is not running')
                row, audit = run_cell(plan, folder, 'honest_qwen_reference', 'proxy', 'reference', upstream=port)
                report['rows'].append({'name': 'honest_qwen_reference', 'row': row, 'audit': audit})
                print(json.dumps({'cell': 'honest_qwen_reference', 'prefix_matches': row['correct'], 'total': row['total']}), flush=True)
        report['status'] = 'ok'
    except (Exception, KeyboardInterrupt) as exc:
        report['status'] = 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed'
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        report['primary_cells_status'] = 'ok' if len(report['rows']) >= 6 and all(
            x.get('oracle_matched') is True for x in report['rows'][:6]) else 'incomplete_or_failed'
        report['reference_status'] = ('omitted_in_replica' if args.adversarial_only else
                                      'ok' if any(x['name'] == 'honest_qwen_reference' for x in report['rows']) else 'incomplete_or_not_started')
        try:
            save(folder / 'integrity_after.json', integrity(plan))
            after_sources = source_hashes()
            save(folder / 'source_hashes_after.json', after_sources)
            if before_sources is None or before_sources != after_sources or git('status', '--porcelain'):
                raise RuntimeError('post-run source integrity/cleanliness check failed')
            report['post_integrity'] = 'ok'
        except Exception as exc:
            report['status'] = 'failed'
            report['post_integrity'] = {'type': type(exc).__name__, 'message': str(exc)}
        if created_eval:
            try:
                # Only remove this run's exact file inside this worktree.
                if not EVAL_PATH.resolve().is_relative_to(ROOT.resolve()):
                    raise RuntimeError('fixture escaped worktree')
                report['eval_fixture_final_sha256'] = digest(EVAL_PATH)
                if report['eval_fixture_final_sha256'] != plan['evalset']['sha256']:
                    raise RuntimeError('owned fixture changed; retained for inspection')
                EVAL_PATH.unlink()
                report['eval_fixture_removed'] = True
            except Exception as exc:
                report['status'] = 'failed'
                report['cleanup_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        report['elapsed_s'] = time.monotonic() - start
        save(folder / 'report.json', report)
    return 0 if report['status'] == 'ok' else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run')
    run.add_argument('--plan', type=Path, required=True)
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--adversarial-only', action='store_true', help='independent replica, explicitly omits model reference')
    cell = sub.add_parser('cell')
    for name in ['name', 'endpoint', 'block', 'result']:
        cell.add_argument('--' + name, required=True)
    cell.add_argument('--kind', choices=['block', 'fixed', 'reference'], required=True)
    args = ap.parse_args()
    return main_run(args) if args.command == 'run' else evaluate_cell(args)


if __name__ == '__main__':
    raise SystemExit(main())

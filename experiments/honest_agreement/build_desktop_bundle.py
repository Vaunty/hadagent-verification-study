"""Build a review bundle from an explicit local allowlist. No network or inference."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / 'experiments/honest_agreement/local'
RETAIN = ('cpu-vA-t1-b512-u128', 'cpu-vA-t4-b512-u128', 'cpu-vA-t8-b512-u128',
          'cpu-vA-t8-b256-u64', 'vulkan-vA-t8-b512-u128', 'cpu-vB-t8-b512-u128')
MUTABLE = ['runtime', 'downloads', 'state', 'results', 'return']


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def copy_file(source, dest):
    if source.is_symlink() or source.name.lower() == '.env':
        raise ValueError('refuse link or secret input')
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)


def relativize(plan):
    plan = deepcopy(plan)
    plan['model']['path'] = 'models/' + Path(plan['model']['path']).name
    plan['evalset']['path'] = 'evalsets/mmlu-fixed-100.jsonl'
    for c in plan['configurations']:
        c['binary'] = f"downloads/extracted/{c['version']}/{c['backend']}/llama-server.exe"
    return plan


def make_plans(original):
    laptop = relativize(original)
    laptop['repeats'] = 1
    laptop['run_timeout_s'] = 1800
    laptop['configurations'] = [c for c in laptop['configurations'] if c['id'] in RETAIN]
    laptop['amendment'] = 'P-005b: timing-only; pending independent consensus'
    desktop = deepcopy(laptop)
    desktop['experiment_timeout_s'] = 28800
    desktop['hardware'] = {'scope': 'one consumer NVIDIA GPU', **{
        k: 'UNRESOLVED_DESKTOP_' + k.upper() for k in ('cpu', 'gpu', 'driver', 'ram', 'os')}}
    desktop['amendment'] = 'P-008 + P-005b: pending RED and independent review'
    for version, backend, letter in [('b11514', 'cuda', 'A'), ('b11513', 'cuda', 'B'),
                                     ('b11513', 'vulkan', 'B')]:
        c = deepcopy(desktop['configurations'][2])
        c.update(id=f'{backend}-v{letter}-t8-b512-u128', version=version, backend=backend,
                 gpu_layers=99, binary=f'downloads/extracted/{version}/{backend}/llama-server.exe',
                 binary_sha256='UNRESOLVED_AFTER_VERIFIED_EXTRACTION',
                 version_output_sha256='UNRESOLVED_AFTER_VERSION_CHECK',
                 runtime_files_sha256={}, release_asset_sha256='UNRESOLVED_FROM_LOCK')
        c.pop('candidate_url', None)
        desktop['configurations'].append(c)
    fp16 = deepcopy(desktop)
    fp16['configurations'] = [deepcopy(desktop['configurations'][6])]
    fp16['configurations'][0]['id'] = 'fp16-cuda-vA-t8-b512-u128'
    fp16['reference_run_id'] = 'fp16-cuda-vA-t8-b512-u128/repeat-0'
    fp16['model'].update(filename='qwen2.5-1.5b-instruct-fp16.gguf',
                         path='downloads/model/qwen2.5-1.5b-instruct-fp16.gguf',
                         sha256='fc89e330deb3fd8fa560f1c0f35a1e2b8da96d59e13445559ed190307a6f5649')
    fp16['model']['candidate_url'] = fp16['model']['candidate_url'].replace('q4_k_m', 'fp16')
    load = deepcopy(desktop)
    load.update(mode='same_endpoint_load', run_timeout_s=3600,
                load_prompt='Write a short explanation of how rain forms.')
    load['configurations'] = [deepcopy(desktop['configurations'][6])]
    load['configurations'][0].update(id='load-cuda-vA-t8-b512-u128', parallel=2, load_workers=1)
    load['reference_run_id'] = 'load-cuda-vA-t8-b512-u128/repeat-0/idle'
    laptop_load = deepcopy(laptop)
    laptop_load.update(mode='same_endpoint_load', run_timeout_s=3600, load_prompt=load['load_prompt'])
    laptop_load['configurations'] = [deepcopy(laptop['configurations'][2])]
    laptop_load['configurations'][0].update(id='load-cpu-vA-t8-b512-u128', parallel=2, load_workers=1)
    laptop_load['reference_run_id'] = 'load-cpu-vA-t8-b512-u128/repeat-0/idle'
    return {'laptop-q4': laptop, 'laptop-load': laptop_load,
            'desktop-q4': desktop, 'desktop-fp16': fp16, 'desktop-load': load}


def python_runtime_pin(path=None):
    pin = {'version': '3.14.4', 'architecture': 'amd64',
           'url': 'https://www.python.org/ftp/python/3.14.4/python-3.14.4-embed-amd64.zip',
           'sha256': 'UNRESOLVED_OFFICIAL_PYTHON_DIGEST_NO_NETWORK_DURING_PACKAGING'}
    if path is None:
        return pin
    supplied = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if any(supplied.get(k) != pin[k] for k in ('version', 'architecture', 'url')):
        raise ValueError('runtime revision, architecture and official URL are fixed')
    if not re.fullmatch(r'[0-9a-f]{64}', supplied.get('sha256', '')):
        raise ValueError('runtime pin needs a publisher SHA-256')
    if not supplied.get('digest_source', '').startswith('https://www.python.org/'):
        raise ValueError('record the official python.org digest source')
    return supplied


def build(destination, runtime_lock=None):
    destination = destination.resolve()
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT, text=True).strip():
        raise ValueError('commit tracked source changes before binding a bundle to HEAD')
    if destination.exists():
        raise FileExistsError('bundle destination already exists; never overwrite a reviewed bundle')
    destination.mkdir(parents=True)
    def cp(src, rel):
        copy_file(ROOT / src, destination / rel)
    tracked = subprocess.check_output(['git', 'ls-files', 'hadagent/src/podl_chain'], cwd=ROOT,
                                     text=True).splitlines()
    for rel in tracked:
        cp(rel, rel)
    for name in ('__init__.py', 'run.py', 'analyze.py', 'prepare_evalset.py',
                 'README.md', 'MANIFEST_2026-10-08.md', 'P005b_PROPOSAL.md'):
        cp('experiments/honest_agreement/' + name, 'experiments/honest_agreement/' + name)
    cp('experiments/__init__.py', 'experiments/__init__.py')
    for name in ('verify_bundle.py', 'prepare_artifacts.py', 'control.py', 'launch.py', 'DESKTOP_RUNBOOK.md'):
        copy_file(ROOT / 'experiments/honest_agreement/desktop' / name, destination / name)
    # Only these runtime distributions are needed by the unmodified package imports.
    packages = {'PyNaCl': ['nacl'], 'cffi': ['cffi'], 'pycparser': ['pycparser'], 'msgpack': ['msgpack']}
    versions = {}
    for name, folders in packages.items():
        dist = importlib.metadata.distribution(name)
        versions[name] = dist.version
        for entry in dist.files or []:
            rel = Path(str(entry))
            if ('..' in rel.parts or '__pycache__' in rel.parts or rel.suffix in ('.pyc', '.pth')):
                continue
            if (rel.parts[0] in folders or rel.name.startswith('_cffi_backend.')
                    or ('.dist-info' in rel.parts[0] and (rel.name in ('METADATA', 'WHEEL')
                                                        or 'license' in str(rel).lower()))):
                copy_file(Path(dist.locate_file(entry)), destination / 'vendor' / rel)
    (destination / 'requirements.txt').write_text(
        '# Inventory of vendored installed packages; do not pip install.\n' +
        '\n'.join(f'{k}=={v}' for k, v in versions.items()) + '\n', encoding='utf-8')
    original = json.loads((LOCAL / 'plan.calibration.json').read_text(encoding='utf-8'))
    write_json(destination / 'plans/original-laptop.relocated.json', relativize(original))
    write_json(destination / 'plans/original-laptop.provenance.json', {
        'original_file_sha256': sha(LOCAL / 'plan.calibration.json'),
        'original_canonical_sha256': 'e6efe29d177017e018385a3e9df2c9d2fe0a563028e288dd21a69ec5f643fa21',
        'copy_note': 'Only local absolute model/eval/binary paths relocated; original retained on laptop.'})
    for name, plan in make_plans(original).items():
        write_json(destination / 'plans' / (name + '.template.json'), plan)
    cp('experiments/honest_agreement/local/models/' + original['model']['filename'],
       'models/' + original['model']['filename'])
    for name in ('mmlu-fixed-100.jsonl', 'mmlu-fixed-100.selection.json'):
        cp('experiments/honest_agreement/local/evalsets/' + name, 'evalsets/' + name)
    for name in ('qwen-LICENSE', 'qwen-README.md', 'llama-LICENSE-b11514'):
        cp('experiments/honest_agreement/local/sources/' + name, 'licenses/' + name)
    for file in (LOCAL / 'sources/mmlu').glob('*'):
        if file.is_file() and (file.name.startswith(('LICENSE-', 'HF-DATASET-CARD-'))):
            copy_file(file, destination / 'licenses' / file.name)
    write_json(destination / 'pilot-failure.json', json.loads(
        (LOCAL / 'results/calibration.failure-summary.json').read_text(encoding='utf-8')))
    releases = json.loads((LOCAL / 'sources/llama-releases.json').read_text(encoding='utf-8'))
    artifacts = []
    for release in releases:
        tag = release['tag_name']
        if tag not in ('b11514', 'b11513'):
            continue
        for asset in release['assets']:
            name = asset['name']
            # Keep one CUDA family: CUDA 12.4, compatible only if the existing driver supports it.
            if (name.endswith(('bin-win-cpu-x64.zip', 'bin-win-vulkan-x64.zip'))
                    or 'win-cuda-12.4-x64' in name):
                checksum = (asset.get('digest') or '').removeprefix('sha256:')
                if len(checksum) != 64:
                    raise ValueError('release has no publisher SHA-256: ' + name)
                artifacts.append({'name': name, 'url': asset['browser_download_url'], 'sha256': checksum,
                                  'bytes': asset['size'], 'version': tag, 'publisher': 'GitHub release asset digest'})
    model_info = json.loads((LOCAL / 'sources/qwen-model.json').read_text(encoding='utf-8'))
    fp = next(s for s in model_info['siblings'] if s['rfilename'].endswith('-fp16.gguf'))
    artifacts.append({'name': fp['rfilename'], 'url':
        f"https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/{model_info['sha']}/{fp['rfilename']}",
        'sha256': fp['lfs']['sha256'], 'bytes': fp['size'], 'publisher': 'HF LFS SHA-256 at frozen revision'})
    for a in artifacts:
        if 'version' in a:
            cached = ROOT / 'tools/llama.cpp/archives' / a['name']
            if cached.exists():
                if sha(cached) != a['sha256'] or cached.stat().st_size != a['bytes']:
                    raise ValueError('cached release archive no longer matches publisher pin')
                copy_file(cached, destination / 'downloads' / a['version'] / a['name'])
    write_json(destination / 'downloads.lock.json', {'artifacts': artifacts,
        'python_runtime': python_runtime_pin(runtime_lock),
        'runtime_note': 'Vendor native modules target CPython 3.14 Windows AMD64; no installation or pip required.',
        'dependency_provenance': 'Copied from existing local venv, versions and every file SHA pinned; not newly publisher-verified wheels.'})
    source_names = ('experiments/honest_agreement/run.py', 'experiments/honest_agreement/analyze.py',
                    'hadagent/src/podl_chain/pdl.py', 'hadagent/src/podl_chain/crypto.py')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    write_json(destination / 'bundle-provenance.json', {'source_commit': commit,
        'source_files_sha256': {n: sha(destination / n) for n in source_names},
        'status': 'OFFLINE REVIEW BUNDLE; unresolved runtime pin and hardware; execution not authorized'})
    # No raw personal paths or environment are copied. Fail on accidental local profile strings.
    for p in destination.rglob('*'):
        if p.is_file() and p.suffix in ('.json', '.jsonl', '.md', '.txt', '.ps1', '.py'):
            content = p.read_text(encoding='utf-8', errors='replace').lower()
            if 'c:\\users\\matth' in content or 'c:/users/matth' in content:
                raise ValueError('personal profile path in bundle: ' + p.relative_to(destination).as_posix())
    files = {p.relative_to(destination).as_posix(): {'sha256': sha(p), 'size': p.stat().st_size}
             for p in sorted(destination.rglob('*')) if p.is_file()}
    write_json(destination / 'bundle-manifest.json', {'schema_version': 1, 'files': files,
                                                   'allowed_mutable_roots': MUTABLE})
    anchor = sha(destination / 'bundle-manifest.json')
    spec = importlib.util.spec_from_file_location('built_bundle_verifier', destination / 'verify_bundle.py')
    verifier = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(verifier)
    verifier.verify(destination, destination / 'bundle-manifest.json', anchor)
    return {'directory': str(destination), 'manifest_sha256': anchor, 'files': len(files),
            'bytes': sum(p['size'] for p in files.values()), 'source_commit': commit}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'experiments/honest_agreement/desktop_bundle')
    parser.add_argument('--zip', action='store_true')
    parser.add_argument('--python-runtime-lock', type=Path,
                        help='optional reviewed official runtime pin; never fetched by this builder')
    args = parser.parse_args()
    result = build(args.output, args.python_runtime_lock)
    if args.zip:
        archive = args.output.with_suffix('.zip')
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_STORED) as z:
            for p in sorted(args.output.rglob('*')):
                if p.is_file():
                    z.write(p, p.relative_to(args.output).as_posix())
        result.update(zip=str(archive), zip_sha256=sha(archive))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

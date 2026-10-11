"""P010 local-only participant; no model library, subprocess, or model-file access.

Lookup/wrong arms serve predetermined benchmark answers. Proxy arm transparently
forwards actual requests to the separately owned local llama-server. Every
completed request is flushed to disk before the response is returned.
"""
import argparse
import hashlib
import http.client
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['lookup', 'wrong', 'proxy'], required=True)
    ap.add_argument('--evalset', type=Path, required=True)
    ap.add_argument('--ready', type=Path, required=True)
    ap.add_argument('--log', type=Path, required=True)
    ap.add_argument('--upstream-port', type=int)
    args = ap.parse_args()
    pairs = [json.loads(x) for x in args.evalset.read_text(encoding='utf-8').splitlines() if x.strip()]
    lookup = {x['prompt']: x['answer'] for x in pairs}
    if len(lookup) != len(pairs):
        raise ValueError('duplicate prompts are not allowed')
    if args.mode == 'proxy' and not 1 <= (args.upstream_port or 0) <= 65535:
        raise ValueError('proxy requires a local upstream port')
    cfg = dict(temperature=0.0, top_k=1, top_p=1.0, n_predict=64)
    with args.log.open('x', encoding='utf-8') as log:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, body):
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.reply(200 if self.path == '/health' else 404, b'{"status":"ok"}')

            def do_POST(self):
                start = time.monotonic()
                row = {'mode': args.mode, 'path': self.path, 'status': 'failed'}
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if self.path != '/completion' or not 0 < size <= 100000:
                        raise ValueError('unexpected request path/size')
                    raw = self.rfile.read(size)
                    row['request_body_sha256'] = hashlib.sha256(raw).hexdigest()
                    request = json.loads(raw)
                    row['request'] = request
                    prompt = request.get('prompt')
                    if not isinstance(prompt, str) or request != {'prompt': prompt, **cfg}:
                        raise ValueError('unexpected decode configuration')
                    row['prompt_sha256'] = hashlib.sha256(prompt.encode()).hexdigest()
                    row['known_prompt'] = prompt in lookup
                    if args.mode == 'proxy':
                        conn = http.client.HTTPConnection('127.0.0.1', args.upstream_port, timeout=115)
                        try:
                            conn.request('POST', '/completion', body=raw, headers={'Content-Type': 'application/json'})
                            upstream = conn.getresponse()
                            row['upstream_http_status'] = upstream.status
                            if upstream.status != 200:
                                raise RuntimeError(f'upstream status {upstream.status}; redirects forbidden')
                            body = upstream.read()
                            row['upstream_body_sha256'] = hashlib.sha256(body).hexdigest()
                        finally:
                            conn.close()
                    else:
                        # Unknown input is not answered from a model or fallback service.
                        content = lookup.get(prompt, '[unknown prompt]') if args.mode == 'lookup' else '[deliberately wrong]'
                        body = json.dumps({'content': content}).encode()
                    response = json.loads(body)
                    output = str(response.get('content') or response.get('completion') or '')
                    row.update(status='ok', response=response, raw_output=output,
                               response_sha256=hashlib.sha256(body).hexdigest())
                    status = 200
                except Exception as exc:
                    row['error'] = {'type': type(exc).__name__, 'message': str(exc)}
                    body, status = b'{"error":"participant failure"}', 500
                row['elapsed_s'] = time.monotonic() - start
                log.write(json.dumps(row, sort_keys=True) + '\n')
                log.flush()
                self.reply(status, body)

        server = HTTPServer(('127.0.0.1', 0), Handler)
        server.timeout = 1
        with args.ready.open('x', encoding='utf-8') as ready:
            json.dump({'host': '127.0.0.1', 'port': server.server_port}, ready)
        server.serve_forever()


if __name__ == '__main__':
    main()

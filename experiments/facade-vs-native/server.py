"""Loopback-only fixture server for the facade-vs-native A/B harness.

Binds 127.0.0.1 only. Serves the booking/orders fixture pages (fixtures.py)
and a /log endpoint that appends every click event to events.jsonl -- the
harness's ground truth. Nothing here operates the desktop or drives a
browser; see runner.py for that, and its README for the required consent.
"""
import argparse
import http.server
import json
import time
import urllib.parse
from pathlib import Path

import re

from pages import PAGES

HERE = Path(__file__).resolve().parent
_SAFE = re.compile(r'[^A-Za-z0-9._-]')


def read_events(events_path, run=None):
    path = Path(events_path)
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in rows if run is None or r.get('run') == run]


def handle_request(raw_path, events_path):
    """Pure request handler: returns (status, content_type, body_bytes). Appends to events_path on /log?action=..

    /log with no `action` returns the event log as JSON (optionally filtered by run): the ground truth.
    """
    parsed = urllib.parse.urlsplit(raw_path)
    query = urllib.parse.parse_qs(parsed.query)
    run = _SAFE.sub('_', (query.get('run') or ['default'])[0])
    route = parsed.path.lstrip('/')
    if route in PAGES:
        return 200, 'text/html; charset=utf-8', PAGES[route](run).encode('utf-8')
    if parsed.path == '/log':
        if 'action' not in query:
            rows = read_events(events_path, run if 'run' in query else None)
            return 200, 'application/json', json.dumps(rows).encode('utf-8')
        event = {'ts': time.time(), 'run': run, 'task': (query.get('task') or [''])[0],
                 'action': query['action'][0], 'id': (query.get('id') or [''])[0]}
        values = {k[2:]: v[0] for k, v in query.items() if k.startswith('v_')}
        if values:
            event['values'] = values
        with Path(events_path).open('a') as fh:
            fh.write(json.dumps(event, sort_keys=True) + '\n')
        return 200, 'text/plain', b'ok'
    return 404, 'text/plain', b''


class Handler(http.server.BaseHTTPRequestHandler):
    events_path = HERE / 'events.jsonl'

    def log_message(self, fmt, *args):
        pass  # keep stdout clean for the runner; events.jsonl is the record

    def do_GET(self):
        status, ctype, payload = handle_request(self.path, self.events_path)
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def make_server(port, events_path):
    """Loopback-only server. Never 0.0.0.0."""
    handler = type('BoundHandler', (Handler,), {'events_path': Path(events_path)})
    return http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8934)
    parser.add_argument('--events', default=str(HERE / 'events.jsonl'))
    args = parser.parse_args()
    Handler.events_path = Path(args.events)
    # 127.0.0.1 only -- never 0.0.0.0. Loopback keeps this off the network.
    httpd = make_server(args.port, args.events)
    print(f'facade-vs-native fixture server on http://127.0.0.1:{args.port} '
          f'(events -> {Handler.events_path})')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

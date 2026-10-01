"""Loopback-only fixture server for the surfaces A/B. Binds 127.0.0.1 only.

GET  /<page>?run=ID      fixture pages (fixtures.page_for)
GET  /log?run=..&action=..&id=..&v_x=..   append one event to events.jsonl (the ground truth); /log with no action reads it back
POST /upload?run=ID      multipart file upload: logs {action: upload, values: {filename, size, sha256}} (the file itself is discarded)
"""
import argparse
import hashlib
import http.server
import json
import re
import threading
import time
import urllib.parse
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path

from fixtures import page_for

HERE = Path(__file__).resolve().parent
_SAFE = re.compile(r'[^A-Za-z0-9._-]')
_lock = threading.Lock()


def read_events(events_path, run=None):
    path = Path(events_path)
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [r for r in rows if run is None or r.get('run') == run]


def append_event(events_path, event):
    with _lock, Path(events_path).open('a') as fh:
        fh.write(json.dumps(event, sort_keys=True) + '\n')


def parse_upload(content_type, body):
    """(filename, size, sha256) of the first file part of a multipart body, or None."""
    message = BytesParser(policy=HTTP).parsebytes(b'Content-Type: ' + content_type.encode() + b'\r\n\r\n' + body)
    if not message.is_multipart():
        return None
    for part in message.iter_parts():
        filename = part.get_filename()
        if filename is not None:
            data = part.get_payload(decode=True) or b''
            return filename, len(data), hashlib.sha256(data).hexdigest()
    return None


def handle_get(raw_path, events_path):
    parsed = urllib.parse.urlsplit(raw_path)
    query = urllib.parse.parse_qs(parsed.query)
    run = _SAFE.sub('_', (query.get('run') or ['default'])[0])
    route = parsed.path.lstrip('/')
    page = page_for(route, run)
    if page is not None:
        return 200, 'text/html; charset=utf-8', page.encode('utf-8')
    if parsed.path == '/log':
        if 'action' not in query:
            return 200, 'application/json', json.dumps(read_events(events_path, run if 'run' in query else None)).encode()
        event = {'ts': time.time(), 'run': run, 'task': (query.get('task') or [''])[0],
                 'action': query['action'][0], 'id': (query.get('id') or [''])[0]}
        values = {k[2:]: v[0] for k, v in query.items() if k.startswith('v_')}
        if values:
            event['values'] = values
        append_event(events_path, event)
        return 200, 'text/plain', b'ok'
    return 404, 'text/plain', b''


def handle_post(raw_path, content_type, body, events_path):
    parsed = urllib.parse.urlsplit(raw_path)
    query = urllib.parse.parse_qs(parsed.query)
    run = _SAFE.sub('_', (query.get('run') or ['default'])[0])
    if parsed.path != '/upload':
        return 404, 'text/plain', b''
    got = parse_upload(content_type, body)
    if got is None:
        return 400, 'text/plain', b'no file'
    filename, size, digest = got
    append_event(events_path, {'ts': time.time(), 'run': run, 'task': 'upload', 'action': 'upload', 'id': 'attachment',
                               'values': {'filename': filename, 'size': str(size), 'sha256': digest}})
    return 200, 'text/plain', b'ok'


class Handler(http.server.BaseHTTPRequestHandler):
    events_path = HERE / 'events.jsonl'

    def log_message(self, fmt, *args):
        pass

    def _send(self, status, ctype, payload):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._send(*handle_get(self.path, self.events_path))

    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length) if length else b''
        self._send(*handle_post(self.path, self.headers.get('Content-Type', ''), body, self.events_path))


def make_server(port, events_path):
    """Loopback-only. Never 0.0.0.0. port 0 picks a free port."""
    handler = type('BoundHandler', (Handler,), {'events_path': Path(events_path)})
    return http.server.ThreadingHTTPServer(('127.0.0.1', port), handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8935)
    parser.add_argument('--events', default=str(HERE / 'events.jsonl'))
    args = parser.parse_args()
    httpd = make_server(args.port, args.events)
    print('surfaces-ab fixture server on http://127.0.0.1:%d (events -> %s)' % (httpd.server_address[1], args.events))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

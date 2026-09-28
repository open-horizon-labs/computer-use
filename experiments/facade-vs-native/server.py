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

from fixtures import render_booking, render_canvas, render_orders

HERE = Path(__file__).resolve().parent


class Handler(http.server.BaseHTTPRequestHandler):
    events_path = HERE / 'events.jsonl'

    def log_message(self, fmt, *args):
        pass  # keep stdout clean for the runner; events.jsonl is the record

    def _send_html(self, body):
        payload = body.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        run = (query.get('run') or ['default'])[0]
        if parsed.path == '/booking':
            return self._send_html(render_booking(run))
        if parsed.path == '/orders':
            return self._send_html(render_orders(run))
        if parsed.path == '/canvas':
            return self._send_html(render_canvas(run))
        if parsed.path == '/log':
            event = {
                'ts': time.time(),
                'run': run,
                'task': (query.get('task') or [''])[0],
                'action': (query.get('action') or [''])[0],
                'id': (query.get('id') or [''])[0],
            }
            with self.events_path.open('a') as fh:
                fh.write(json.dumps(event, sort_keys=True) + '\n')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'ok')
            return
        self.send_response(404)
        self.end_headers()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8934)
    parser.add_argument('--events', default=str(HERE / 'events.jsonl'))
    args = parser.parse_args()
    Handler.events_path = Path(args.events)
    # 127.0.0.1 only -- never 0.0.0.0. Loopback keeps this off the network.
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'facade-vs-native fixture server on http://127.0.0.1:{args.port} '
          f'(events -> {Handler.events_path})')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()

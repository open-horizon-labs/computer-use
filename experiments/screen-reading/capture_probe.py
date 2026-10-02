"""Live, read-only isolated-browser screen probe; never run by offline gates.

Launches an owned browser on the configured agent display, serves a synthetic
booking fixture on loopback, captures through Driver and closes owned resources.
Usage: .venv-facade/bin/python experiments/screen-reading/capture_probe.py --output /tmp/screen-probe
"""
import argparse
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'computer_use'))
sys.path.append(str(ROOT / 'experiments/facade-vs-native'))
from pages import PAGES
from core import Facade
from agent_browser import AgentBrowser
from dom import _tab_of
from screen import native_capture, validate_image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = PAGES['booking']('screen-reading').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):pass

    srv = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    f = Facade(agent_browser=AgentBrowser())
    result = {'date': datetime.now(timezone.utc).isoformat(), 'surface': 'isolated browser on agent display',
              'obo_tested': False, 'task': 'read synthetic booking screen'}
    try:
        pid, wid = f.agent_browser.window(f)
        f.driver.call('browser_prepare', {'pid': pid, 'window_id': wid, 'strategy': {'kind': 'existing_profile'}, 'session': f.session})
        bound = f.driver.call('get_browser_state', {'pid': pid, 'window_id': wid, 'session': f.session})
        tab = _tab_of(bound, f, pid)
        f.driver.call('browser_navigate', {'target_id': bound['target_id'], 'tab_id': tab['tab_id'], 'session': f.session,
                                         'url': 'http://127.0.0.1:%d/booking' % srv.server_port})
        result['driver_version'] = f.driver_version
        try:
            image, mime, meta, title = native_capture(f, pid, wid)
            validate_image(image, mime)
            (args.output / 'native.png').write_bytes(image)
            result['native'] = 'capture accepted; image interpretation requires visual inspection'
        except Exception as error:
            result['native'] = str(error).split(':')[0]
        started = time.monotonic()
        out = f.look(pid=pid, window_id=wid, screen=True)
        result['look_ms'] = round((time.monotonic() - started) * 1000)
        image = out.pop('_screen_image', None)
        result['response'] = out
        result['image_base64_bytes'] = len(image['data']) if image else 0
        if image:(args.output / 'browser.png').write_bytes(base64.b64decode(image['data']))
        (args.output / 'live-capture.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
        return 0 if out.get('status') == 'ok' and image else 1
    finally:
        f.shutdown()
        srv.shutdown()
        srv.server_close()


if __name__ == '__main__':raise SystemExit(main())

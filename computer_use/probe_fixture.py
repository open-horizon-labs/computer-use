"""The bundled smoke target of `python -m computer_use doctor --probe` (#64): a loopback-only booking page, served briefly.

A small copy of the booking shape of experiments/facade-vs-native (a list of records with a Book button each and a status line that reads
"Booked: ..." after a press), so the probe can run one look and one verified do without the network and without a repo checkout of the experiments.
Binds 127.0.0.1 only, on a port the OS picks; nothing is logged or written.
"""
import html
import http.server
import threading

SLOTS = (('Dr. Priya Shah', 'Intake', '45 min', '9:00 AM'), ('Dr. Morgan Reyes', 'Follow-up', 'half-hour', '1:45 PM'),
         ('Dr. Sam Okafor', 'Follow-up', '20 min', '2:30 PM'), ('Dr. Lena Brandt', 'Telehealth', '30 min', '3:15 PM'))
FIRST_PROVIDER = SLOTS[0][0]
BOOKED = 'Booked:'


def render():
    items = []
    for provider, service, duration, start in SLOTS:
        label = '%s, %s, %s' % (provider, duration, start)
        items.append('<li><div>%s</div><div>%s</div><div>%s</div><div>Starts %s</div>'
                     '<button onclick="document.getElementById(\'status\').textContent=\'%s %s\'">Book</button></li>'
                     % (html.escape(provider), html.escape(service), html.escape(duration), html.escape(start), BOOKED, html.escape(label, quote=True)))
    return ('<!doctype html><html><head><meta charset="utf-8"><title>Clinic Slots probe</title></head><body><h1>Clinic Slots</h1>'
            '<p id="status" role="status">Pick a slot</p><ul>%s</ul></body></html>' % ''.join(items))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        body = render().encode('utf-8') if self.path.split('?')[0] in ('/', '/booking') else b''
        self.send_response(200 if body else 404)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve():
    """(server, url) of the page on a free loopback port; call server.shutdown() and server.server_close() when done."""
    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, 'http://127.0.0.1:%d/booking' % httpd.server_address[1]

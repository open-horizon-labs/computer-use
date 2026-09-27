"""Synthetic booking fixture. Hidden oracle is never returned to the controller."""
import json, random, threading, html
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
GOAL='Book the earliest available 30-minute appointment strictly after 2 PM with Alex. If none exists, join the waitlist. Confirm the booking when asked.'
runs={}
def create(seed):
    r=random.Random(seed)
    times=r.sample([845,855,870,885,900,915,930,945,960],6)
    slots=[dict(id=str(i),person=r.choice(['Alex','Alex','Sam']),minute=t,duration=r.choice([30,30,60]),available=True) for i,t in enumerate(times)]
    if seed%4==0:
        for s in slots: s['person']='Sam'
    else:
        for s in slots[:2]: s.update(person='Alex',duration=30)
    for s in slots:
        t=s['minute'];s['label']=f"{s['person']} | {t//60-12}:{t%60:02d} PM | {s['duration']} minutes"
    eligible=sorted([s for s in slots if s['person']=='Alex' and s['duration']==30 and s['minute']>840],key=lambda s:s['minute'])
    lost=eligible[0]['id'] if seed%4==2 and eligible else None
    r.shuffle(slots)
    return dict(seed=seed,slots=slots,lost=lost,confirm=seed%2==1,stage='slots',notice='',selected=None,outcome=None,actions=[],mistakes=0)
def best(run):
    s=[s for s in run['slots'] if s['available'] and s['person']=='Alex' and s['duration']==30 and s['minute']>840]
    return min(s,key=lambda s:s['minute'])['id'] if s else 'waitlist'
def act(run,action):
    expected=best(run) if run['stage']=='slots' else 'confirm'
    run['actions'].append(action)
    if action!=expected: run['mistakes']+=1
    if run['stage']=='confirm':
        if action=='confirm': run.update(stage='done',outcome=run['selected'])
        return
    if action=='waitlist': run.update(stage='done',outcome='waitlist');return
    chosen=next((s for s in run['slots'] if s['id']==action and s['available']),None)
    if chosen is None:return
    if action==run['lost']:
        chosen['available']=False;run.update(notice='That slot was just taken. Choose another appointment.',lost=None);return
    run['selected']=action
    run.update(stage='confirm' if run['confirm'] else 'done',outcome=None if run['confirm'] else action)
def page(run):
    content=f'<h1>Appointment booking</h1><p>{GOAL}</p><p>{run["notice"]}</p>'
    if run['stage']=='slots':
        for s in run['slots']:
            if s['available']:content+=f'<button onclick="act(\'{s["id"]}\')">Book {s["label"]}</button>'
            else:content+=f'<p>Unavailable: {s["label"]}</p>'
        content+='<button onclick="act(\'waitlist\')">Join waitlist</button>'
    elif run['stage']=='confirm':
        s=next(s for s in run['slots'] if s['id']==run['selected'])
        content+=f'<h2>Confirm {s["label"]}</h2><button onclick="act(\'confirm\')">Confirm booking</button>'
    else:content+='<h2>Task complete</h2>'
    return ('<html><head><title>Booking benchmark</title><style>body{font:18px system-ui;margin:30px}button{display:block;margin:12px;padding:10px}</style></head><body>'+content+'''<script>async function act(a){await fetch(location.pathname+'/act',{method:'POST',body:a});location.reload()}</script></body></html>''').encode()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        parts=urlparse(self.path).path.strip('/').split('/')
        if parts[0]=='favicon.ico':self.send_response(204);self.end_headers();return
        key=parts[0]
        if key not in runs:runs[key]=create(int(parse_qs(urlparse(self.path).query).get('seed',['0'])[0]))
        run=runs[key]
        if len(parts)>1 and parts[1]=='oracle':
            data=json.dumps(dict(done=run['stage']=='done',correct=run['stage']=='done' and run['mistakes']==0,mistakes=run['mistakes'],actions=run['actions'],outcome=run['outcome'])).encode();kind='application/json'
        else:data=page(run);kind='text/html'
        self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def do_POST(self):
        key=self.path.strip('/').split('/')[0];action=self.rfile.read(int(self.headers['Content-Length'])).decode();act(runs[key],action)
        self.send_response(204);self.end_headers()
def start():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();return server

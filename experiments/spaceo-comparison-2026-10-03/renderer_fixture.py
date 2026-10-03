"""Synthetic loopback fixture and independent event oracle; no desktop operations."""
import http.server,json,urllib.parse,time
CASES=['static','duplicate_context','reorder','insert_before','meaning_change','removed','disabled','navigation','form']
MUTATIONS={
 'reorder':"document.getElementById('rows').appendChild(document.getElementById('record-target'))",
 'insert_before':"let s=document.createElement('section');s.innerHTML='<button id=inserted data-meaning=decoy onclick=send(this.dataset.meaning)>Inserted decoy</button>';document.getElementById('rows').prepend(s)",
 'meaning_change':"document.getElementById('target').dataset.meaning='decoy';document.getElementById('target').textContent='Reserve Dr. Rao 16:00';document.getElementById('record-target').firstChild.textContent='Dr. Rao 16:00, different appointment'",
 'removed':"document.getElementById('record-target').remove()",
 'disabled':"document.getElementById('target').disabled=true",
}
def make_server(events):
 class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   u=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(u.query);run=q.get('run',['unknown'])[0]
   if u.path=='/event':
    row={'run':run,'meaning':q.get('meaning',[''])[0],'values':{k[2:]:v[0] for k,v in q.items() if k.startswith('v_')},'ts':time.time()};events.append(row);body=b'ok';kind='text/plain'
   else:
    case=q.get('case',['static'])[0];changed=q.get('doc',['initial'])[0]!='initial'
    send="function send(meaning,extra=''){fetch('/event?run='+encodeURIComponent("+json.dumps(run)+")+'&meaning='+encodeURIComponent(meaning)+extra)}"
    first=f'<section id=record-target>Dr. Shah 15:00, intended appointment<button id=target data-meaning={"decoy" if changed else "target"} onclick=send(this.dataset.meaning)>{"Different operation" if changed else "Book" if case=="duplicate_context" else "Reserve Dr. Shah 15:00"}</button></section>'
    second='<section id=record-decoy>Dr. Rao 16:00, different appointment<button id=decoy data-meaning=decoy onclick=send(this.dataset.meaning)>'+('Book' if case=='duplicate_context' else 'Reserve Dr. Rao 16:00')+'</button></section>'
    if case=='duplicate_context':first,second=second,first
    if case=='form':
     content="<form onsubmit=\"event.preventDefault();send('submit','&v_name='+encodeURIComponent(document.getElementById('name').value)+'&v_note='+encodeURIComponent(document.getElementById('note').value))\"><label>Name<input id=name aria-label=Name></label><label>Note<textarea id=note aria-label=Note></textarea></label><button id=submit>Submit intake</button></form>"
    else:content='<div id=rows>'+first+second+'</div>'
    body=('<!doctype html><meta charset=utf-8><title>Controlled renderer trial</title><style>body{font:20px sans-serif;background:#f3f4f5;padding:30px}section{padding:18px;margin:12px;border:2px solid #234}button,input,textarea{font:18px sans-serif;margin:12px;padding:12px}</style>'+content+'<script>'+send+'</script>').encode();kind='text/html'
   self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 return http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)

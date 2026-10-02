"""Own a synthetic AppKit window on a virtual display; independent event scoring."""
import json,subprocess,sys,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'computer_use'))
from agent_display import AgentDisplay
from core import Driver
folder=Path('/tmp/cua-mixed-bench');result=folder/'mac-state.json';display=AgentDisplay(mode='required');rect=display.launch_rect();proc=None
print(json.dumps({'display':rect}),flush=True)
# AppKit y grows upward; use NSScreen coordinates from the app's screen selection.
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  data=result.read_bytes() if result.exists() else b'{"events":[]}'
  self.send_response(200);self.end_headers();self.wfile.write(data)
 def do_POST(self):
  global proc
  if proc is not None:
   proc.terminate();proc.wait(5)
  result.unlink(missing_ok=True)
  rect=display.launch_rect()  # Other test sessions can change display layout.
  proc=subprocess.Popen([str(folder/'OH Benchmark.app/Contents/MacOS/OHBenchmark'),str(result),str(rect['x']+50),str(rect['y']+50)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  # Read only the new fixture's exact PID; never manipulate a shared app.
  try:
   driver=Driver();deadline=time.monotonic()+8;window=None
   while time.monotonic()<deadline:
    found=driver.call('list_windows',{}).get('windows',[])
    window=next((w for w in found if w.get('pid')==proc.pid),None)
    if window:break
    time.sleep(.1)
   if not window:raise RuntimeError('owned native fixture window not found')
   # Initial AppKit position is on the owned virtual display; preserve the fresh bounds as preflight evidence.
   (folder/'mac-window.json').write_text(json.dumps(window))
   payload=json.dumps({'ready':True,'pid':proc.pid,'window_id':window['window_id']}).encode();self.send_response(200)
  except Exception as error:
   proc.terminate();proc.wait(5);payload=json.dumps({'error':str(error)}).encode();self.send_response(503)
  self.end_headers();self.wfile.write(payload)
try:ThreadingHTTPServer(('127.0.0.1',8987),Handler).serve_forever()
finally:
 if proc and proc.poll() is None:proc.terminate();proc.wait(5)
 display.stop()

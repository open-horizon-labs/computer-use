import json, subprocess, sys, time, urllib.request, urllib.error
r=subprocess.run(['op','read','op://Fleet/Typesafe.ai Jev API Key/credential'],capture_output=True,text=True,timeout=30)
if r.returncode or not r.stdout.strip():
 print(json.dumps({'ready':False}),flush=True); sys.exit(1)
key=r.stdout.strip()
print(json.dumps({'ready':True}),flush=True)
for line in sys.stdin:
 started=time.perf_counter()
 try:
  body=json.loads(line)
  request=urllib.request.Request('https://api.typesafe.ai/v1/systemone',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  try:
   response=urllib.request.urlopen(request,timeout=25)
  except urllib.error.HTTPError as e:
   response=e
  content=response.read().decode()
  if key in content: raise RuntimeError('secret reflection')
  print(json.dumps({'status':response.status,'content':content,'provider_ms':(time.perf_counter()-started)*1000}),flush=True)
 except Exception as e:
  print(json.dumps({'error_type':type(e).__name__,'provider_ms':(time.perf_counter()-started)*1000}),flush=True)

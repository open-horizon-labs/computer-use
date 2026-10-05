"""Two additional diagnostic reproductions; excluded from the scored trial batch."""
import sys,json
from run_decisions import *
client=FleetClient()
try:
 policy=TypeSafeJevPolicy(api_key='remote-fleet-placeholder',client=client)
except Exception:
 client.close()
 raise
rows=[]
try:
 for name in ('native_form','modal_recovery'):
  f=Fixture()
  try:
   if name=='modal_recovery':f.mutate('sheet')
   task,check=native_case(name)
   with MacOSAXBackend(f.pid) as backend:
    row=run_one(name,3,backend,task,policy,lambda:check(f.state()))
   row['fixture_state']=f.state();rows.append(row)
  finally:f.close()
finally:client.close()
(HERE / 'native-diagnostics.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))

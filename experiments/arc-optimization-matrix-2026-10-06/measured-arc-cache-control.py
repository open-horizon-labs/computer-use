import os,sys,json,time,statistics
from pathlib import Path
sys.path.insert(0,'/tmp/computer-use-arc-review-20261005/experiments/arc-cua-comparison-2026-10-05')
import run as r
from arc_cua.backends import MacOSAXBackend
v=r.candidate_versions();out={**v,'scope':'Current Arc cache control: two warmup pairs and twenty alternating pairs; omitted-notification adversary','results':[]}
f=r.Fixture()
try:
 window=r.wait_for(lambda:r.windows(f.pid).get('Arc Bench Form'))
 with MacOSAXBackend(f.pid,cache=False) as full,MacOSAXBackend(f.pid,cache=True) as cached:
  for rep in range(22):
   for label,backend in ([('full',full),('cached',cached)] if rep%2==0 else [('cached',cached),('full',full)]):
    t=time.perf_counter();snap=backend.observe(window);ms=(time.perf_counter()-t)*1000
    assert any(x.name=='Submit' for x in snap.elements)
    out['results'].append({'mode':label,'rep':rep,'ms':ms,'elements':len(snap.elements)})
  # Explicitly model a target application that fails to emit a label-change notification.
  feed=cached._cache.feed;original=feed.drain
  def omitted_notifications():
   original();return []
  feed.drain=omitted_notifications
  f.mutate('label')
  out['independent_label']=f.state()['submit_label']
  for label,backend in [('full',full),('cached_missing_notification',cached)]:
   snap=backend.observe(window)
   out[label+'_labels']=[x.name for x in snap.elements if 'Submit' in x.name]
 finally_placeholder=0
finally:f.close()
Path('/tmp/cua-arc-optimizations-20261006/arc-cache-control-results.json').write_text(json.dumps(out,indent=2))
print(json.dumps({k:v for k,v in out.items() if k.endswith('_labels') or k=='independent_label'}))
for m in ('full','cached'):print(m,statistics.median(x['ms'] for x in out['results'] if x['mode']==m and x['rep']>=2))

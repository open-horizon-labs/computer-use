"""Retain topology only after fresh child-edge and dynamic-attribute reads."""
import sys,time,json,statistics
from pathlib import Path
sys.path.insert(0,'/tmp/computer-use-arc-review-20261005/experiments/arc-cua-comparison-2026-10-05')
import run as r
from arc_cua.backends.macos_ax import MacOSAXBackend

class FreshValidatedTopology(MacOSAXBackend):
 def __init__(self,pid):
  super().__init__(pid,cache=False);self.topology={};self.seen=set();self.reused=0;self.replaced=0;self.reads=0
 def observe(self,*args,**kwargs):
  self.seen=set();result=super().observe(*args,**kwargs)
  self.topology={ref:children for ref,children in self.topology.items() if ref in self.seen}
  return result
 def _node(self,AS,ref,element_id,parent_id,refresh,row=None):
  # Same complete fresh batch, actions, state, geometry and AXChildren as baseline.
  node=self._read_node(AS,ref,element_id,parent_id,row);self.reads+=1;self.seen.add(ref)
  old=self.topology.get(ref)
  if old is not None and old==node.children:
   node.children=old;self.reused+=1
  else:
   self.topology[ref]=node.children;self.replaced+=int(old is not None)
  return node,False
 def close(self):
  self.topology.clear();super().close()

def projection(snapshot):
 return [(e.role,e.name,e.value,e.enabled,e.bounds,e.actions,e.guard,e.parent_id) for e in snapshot.elements]

def main():
 versions=r.candidate_versions()
 arc=r.MCP([sys.executable,'-m','arc_cua','mcp'],'arc');native=r.MCP(['cua-driver','mcp','--socket',str(Path.home()/'Library/Caches/cua-driver/cua-driver.sock')],'native')
 try:r.verify_servers(versions,arc,native)
 finally:arc.close();native.close()
 r.HERE=Path('/tmp/cua-arc-performance-20261006/structure-wakeups')
 f=r.Fixture();backends=[]
 try:
  window=r.wait_for(lambda:r.windows(f.pid).get('Arc Bench Form'))
  baseline=MacOSAXBackend(f.pid,cache=False);candidate=FreshValidatedTopology(f.pid);backends=[baseline,candidate]
  for backend in backends:backend.open()
  out={'versions':versions,'scope':'Arc OS-level node reader microbenchmark; no Cua speed claim','rows':[]}
  for rep in range(22):
   if rep==2:f.mutate('label')
   if rep==8:f.mutate('value')
   if rep==12:f.mutate('replace')
   if rep==16:f.mutate('disable')
   captures={}
   for mode,b in ([('full',baseline),('topology',candidate)] if rep%2==0 else [('topology',candidate),('full',baseline)]):
    before=candidate.reads;start=time.perf_counter();snap=b.observe(window_id=window);elapsed=(time.perf_counter()-start)*1000
    captures[mode]=snap
    out['rows'].append({'rep':rep,'mode':mode,'warmup':rep<2,'ms':elapsed,'node_reads':candidate.reads-before if mode=='topology' else None,'nodes':len(snap.elements)})
   # IDs are session-local; compare state/geometry/action labels without IDs.
   a=[x[:-1] for x in projection(captures['full'])];b=[x[:-1] for x in projection(captures['topology'])]
   assert a==b,'fresh output differs'
   expected_label='Replacement Submit' if rep>=12 else 'Changed Submit' if rep>=2 else 'Submit'
   assert any(e.name==expected_label for e in captures['topology'].elements)
   if rep>=8:assert any(e.name=='Full name' and e.value=='changed without notification' for e in captures['topology'].elements)
   if rep>=12:assert not any(e.name in ['Changed Submit','Submit'] for e in captures['topology'].elements)
   if rep>=16:assert any(e.name==expected_label and not e.enabled for e in captures['topology'].elements)
   out['topology_reuses']=candidate.reused;out['edge_replacements']=candidate.replaced
   Path('/tmp/cua-arc-performance-20261006/structure-wakeups/structure-results.json').write_text(json.dumps(out,indent=2))
  print(json.dumps({m:statistics.median(x['ms'] for x in out['rows'] if x['mode']==m and not x['warmup']) for m in ['full','topology']}),flush=True)
 finally:
  for b in backends:b.close()
  f.close()
if __name__=='__main__':main()

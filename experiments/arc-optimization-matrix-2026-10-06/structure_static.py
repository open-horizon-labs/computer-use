import sys,time,json,random,statistics,dataclasses
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from structure import FreshValidatedTopology,r,MacOSAXBackend
from arc_cua.backends import macos_ax as ax

class FreshNoReuse(MacOSAXBackend):
 def _node(self,AS,ref,element_id,parent_id,refresh,row=None):
  return self._read_node(AS,ref,element_id,parent_id,row),refresh

def published(snapshot):
 positions={e.id:i for i,e in enumerate(snapshot.elements)}
 elements=[]
 for element in snapshot.elements:
  fields={f.name:getattr(element,f.name) for f in dataclasses.fields(element) if f.name not in ['id','parent_id']}
  fields['parent_position']=positions.get(element.parent_id) if element.parent_id is not None else None
  assert element.parent_id is None or element.parent_id in positions
  elements.append(fields)
 return {'application':snapshot.application,'window':snapshot.window,'context':dict(snapshot.context),'revision':snapshot.revision,'elements':elements,'screenshot':snapshot.screenshot}

def main():
 versions=r.candidate_versions();arc=r.MCP([sys.executable,'-m','arc_cua','mcp'],'arc');native=r.MCP(['cua-driver','mcp','--socket',str(Path.home()/'Library/Caches/cua-driver/cua-driver.sock')],'native')
 try:r.verify_servers(versions,arc,native)
 finally:arc.close();native.close()
 r.HERE=Path(__file__).parent;f=r.Fixture();backends={};restores=[]
 try:
  window=r.wait_for(lambda:r.windows(f.pid).get('Arc Bench Form'))
  backends={'full':MacOSAXBackend(f.pid,cache=False),'fresh_override':FreshNoReuse(f.pid,cache=False),'topology':FreshValidatedTopology(f.pid)}
  for backend in backends.values():backend.open()
  AS,_=ax._frameworks();counts={}
  for name in ['AXUIElementCopyMultipleAttributeValues','AXUIElementCopyAttributeValue','AXUIElementCopyActionNames','AXUIElementIsAttributeSettable']:
   old=getattr(AS,name);restores.append((AS,name,old))
   def counted(*args,_old=old,_name=name,**kwargs):
    counts[_name]=counts.get(_name,0)+1
    return _old(*args,**kwargs)
   setattr(AS,name,counted)
  out={'versions':versions,'scope':'Arc retained-topology microbenchmark; all fresh semantic fields, geometry, actions and parent relationships; no native Cua speed claim','rows':[],'adversaries':[]}
  for mutation in ['label','value','replace','disable']:
   f.mutate(mutation);captures={mode:backend.observe(window) for mode,backend in backends.items()}
   assert published(captures['full'])==published(captures['fresh_override'])==published(captures['topology'])
   state=f.state();candidate=captures['topology'];label=state['submit_label']
   assert any(e.name==label for e in candidate.elements)
   if mutation in ['value','replace','disable']:assert any(e.name=='Full name' and e.value==state['name'] for e in candidate.elements)
   if mutation=='replace':assert label=='Replacement Submit' and not any(e.name=='Changed Submit' for e in candidate.elements)
   if mutation=='disable':assert any(e.name==label and not e.enabled for e in candidate.elements)
   out['adversaries'].append({'mutation':mutation,'all_published_fields_equal':True,'independent_fixture_oracle':True,'notifications_used':False})
  rng=random.Random(617);orders=[['full','fresh_override','topology'],['topology','full','fresh_override'],['fresh_override','topology','full']]*14;rng.shuffle(orders)
  for rep,order in enumerate(orders):
   captures={};before_reuse=backends['topology'].reused
   for mode in order:
    counts.clear();start=time.perf_counter();captures[mode]=backends[mode].observe(window);elapsed=(time.perf_counter()-start)*1000
    out['rows'].append({'mode':mode,'rep':rep,'warmup':rep<6,'ms':elapsed,'native_api_calls':dict(counts),'elements':len(captures[mode].elements)})
   assert published(captures['full'])==published(captures['fresh_override'])==published(captures['topology'])
   calls=[row['native_api_calls'] for row in out['rows'][-3:]];assert calls[0]==calls[1]==calls[2],'API work differs'
   assert backends['topology'].reused>before_reuse,'reuse branch not forced'
   time.sleep(rng.uniform(.001,.009))
  out['medians_ms']={m:statistics.median(x['ms'] for x in out['rows'] if x['mode']==m and not x['warmup']) for m in backends}
  Path(__file__).with_name('structure-static-results.json').write_text(json.dumps(out,indent=2));print(json.dumps(out['medians_ms']),flush=True)
 finally:
  for module,name,old in restores:setattr(module,name,old)
  for b in backends.values():b.close()
  f.close()
if __name__=='__main__':main()

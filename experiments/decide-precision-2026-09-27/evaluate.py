"""Frozen full-pool calibration/test; thresholds chosen without test labels."""
import json,time,gc,itertools
from pathlib import Path
import torch
from gliner2 import AutoExtractor
from fit import ROOT,OLD,BASE,LABELS,DESC,read

def unwrap(x):
 value=x.get('classifications',x)['label'];return value['label'],value['confidence']
def score(model,texts,schema):
 result=[]
 with torch.inference_mode():
  for i in range(0,len(texts),8):
   result.extend(model.batch_classify_text(texts[i:i+8],schema,batch_size=8,include_confidence=True))
 return [dict(label=unwrap(x)[0],score=unwrap(x)[1] if unwrap(x)[0]=='matches' else 0) for x in result]
from selection import choose, metrics

def main():
 torch.set_num_threads(4);splits=json.loads((ROOT/'pool-splits.json').read_text());allresults={}
 for variant in ['pilot','six','described','hard']:
  directory=OLD if variant=='pilot' else ROOT/variant
  if not (directory/'adapter/final/adapter_config.json').exists():
   allresults[variant]={'status':'missing_checkpoint'};continue
  model=AutoExtractor.from_pretrained(BASE,local_files_only=True).to('cuda');model.load_adapter(str(directory/'adapter/final'));model.eval();model.processor.change_mode(is_training=False)
  schema={'label':DESC if variant=='described' else LABELS}
  # Audit serialized descriptions rather than trusting source dictionaries.
  encoded=model._classification_schema(schema).build()
  token_schema=json.loads(json.dumps(encoded));token_schema['classifications'][0]['true_label']=['matches'] # constant placeholder for length audit only
  out={'variant':variant,'schema':encoded,'splits':{}}
  paired=read(OLD/'validation.jsonl');pred=score(model,[x['text'] for x in paired],schema);tp=sum(x['label']=='matches' and y['label']=='matches' for x,y in zip(pred,paired));fp=sum(x['label']=='matches' and y['label']!='matches' for x,y in zip(pred,paired));correct=sum(x['label']==y['label'] for x,y in zip(pred,paired))
  out['paired']={'n':len(pred),'correct':correct,'tp':tp,'fp':fp,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/100}
  for split,rows in splits.items():
   answers=[]
   for r in rows:
    texts=['Task and context:\n'+r['query']+'\nCandidate control:\n'+c for c in r['candidates']]
    lengths=[]
    for text in texts:
     lengths.append(model.processor._collate_batch([(text,token_schema)],max_len=None,error_policy='raise').input_ids.shape[1])
    base={'id':r['id'],'gold':r['gold'],'max_tokens':max(lengths),'n':len(texts)}
    if max(lengths)>512:answers.append(dict(base,deferred='token_budget'));continue
    start=time.perf_counter();scores=score(model,texts,schema);answers.append(dict(base,scores=scores,ms=(time.perf_counter()-start)*1000))
   out['splits'][split]=answers
  grid=[]
  for t,m in itertools.product([.5,.9,.95,.99,.999,.9999,.99999],[0,.001,.01,.1]):grid.append({'threshold':t,'margin':m,**metrics(out['splits']['calibration'],t,m)})
  eligible=[x for x in grid if x['accepted']>=5 and x['precision']>=.95 and x['target_removed_acceptances']==0]
  selected=max(eligible,key=lambda x:(x['coverage'],x['precision'],x['threshold'])) if eligible else None
  out['calibration_grid']=grid;out['selected']=selected
  out['test_default']=metrics(out['splits']['test'],.5,0)
  out['test_gated']=metrics(out['splits']['test'],selected['threshold'],selected['margin']) if selected else {'tasks':len(splits['test']),'accepted':0,'coverage':0,'precision':None,'reason':'no_calibration_policy_qualified'}
  (ROOT/(variant+'-evaluation.json')).write_text(json.dumps(out,indent=2)+'\n');allresults[variant]={k:out[k] for k in ('paired','selected','test_default','test_gated')};(ROOT/'evaluation-summary.json').write_text(json.dumps(allresults,indent=2)+'\n');print(json.dumps({'variant':variant,**allresults[variant]}),flush=True)
  del model;gc.collect();torch.cuda.empty_cache()
if __name__=='__main__':main()

"""Validate saved adapter and reversed-label inference after the training process exits."""
import json,time,hashlib,importlib.metadata
from pathlib import Path
import torch
from gliner2 import AutoExtractor
from run import OUT,BASE,read,evaluate,LABELS

torch.set_num_threads(4)
model=AutoExtractor.from_pretrained(BASE,local_files_only=True).to('cuda')
model.load_adapter(str(OUT/'adapter/final'))
model.eval();model.processor.change_mode(is_training=False)
rows=read(OUT/'validation.jsonl')
result=evaluate(model,rows,'reloaded')
original=json.loads((OUT/'final.json').read_text());reload=json.loads((OUT/'reloaded.json').read_text())
check={'reload':result,'prediction_agreement':sum(a['prediction']==b['prediction'] for a,b in zip(original,reload)),'n':len(rows),'versions':{p:importlib.metadata.version(p) for p in ('gliner2','torch','transformers','peft')}}
with torch.inference_mode():
 results=model.batch_classify_text([x['text'] for x in rows[:32]],{'label':list(reversed(LABELS))},batch_size=8,include_confidence=True)
labels=[]
for x in results:
 value=x.get('classifications',x)['label']
 labels.append(value.get('label') if isinstance(value,dict) else value)
check['reversed_label_order_agreement_32']=sum(x==y['prediction'] for x,y in zip(labels,reload[:32]))
check['adapter_sha256']={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (OUT/'adapter/final').rglob('*') if p.is_file()}
(OUT/'reload-check.json').write_text(json.dumps(check,indent=2)+'\n');print(json.dumps(check),flush=True)

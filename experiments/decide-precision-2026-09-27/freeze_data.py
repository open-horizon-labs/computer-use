"""Freeze reviewed negatives and exploratory application-disjoint pool splits."""
import json,random,hashlib
from pathlib import Path
r=Path('/training-run/decide-precision-20260927');old=Path('/training-run/decide-binary-20260927')
read=lambda p:[json.loads(x) for x in Path(p).read_text().splitlines()]
proposals=json.loads((r/'explicit-proposals.json').read_text())
approved=[1,2,4,7,8,9,10,11,14,16,17,18,19,20,23,24,25,26,27,30,31,32,33,34,35,36,37,39,40,41,44,46,47,48,49,50,51,52,55,59,60,64,68]
review=[];by={}
for i in approved:
 p=proposals[i];by[p['source_id']]=p
 review.append({'proposal_index':i,'source_id':p['source_id'],'query':p['query'],'gold':p['gold'],'negative':p['candidate'],'judgment':'approved for training','reason':'Visible target/operation differs from the explicitly requested target/operation; not accepted merely because candidate differs from demonstrated ID.','reviewer':'Codex self-review of displayed task and explicit control labels; no independent human review'})
tr=read(old/'train.jsonl');changes=0
for x in tr:
 if x['label']=='does_not_match' and x['source_id'] in by:
  p=by[x['source_id']];new='Task and context:\n'+p['query']+'\nCandidate control:\n'+p['candidate']
  if x['text']!=new:changes+=1
  x.update(text=new,id=x['source_id']+':'+str(p['candidate_index']),hard_reviewed=True);x.pop('tokens',None)
(r/'hard-train.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in tr));(r/'hard-review.json').write_text(json.dumps(review,indent=2))
va=read('/training-run/quick-1000-data/validation.jsonl');apps=sorted({x['query'].split('\n')[0] for x in va});random.Random(929).shuffle(apps);half=len(apps)//2
parts={}
for name,aset in [('calibration',set(apps[:half])),('test',set(apps[half:]))]:
 rows=[x for x in va if x['query'].split('\n')[0] in aset];random.Random(930).shuffle(rows);parts[name]=rows[:24]
 assert len(parts[name])==24
trainapps={x['app'] for x in tr};assert not trainapps&set(apps)
(r/'pool-splits.json').write_text(json.dumps(parts,indent=2))
manifest={'training_pairs':1500,'reviewed_negatives':len(review),'changed_negatives':changes,'calibration_tasks':24,'test_tasks':24,'split':'application-disjoint calibration/test, both disjoint from training; existing exploratory validation corpus, not claimed untouched','seed':929,'evaluation':'all offered candidates plus paired target-removed no-demonstrated-target probes; no model receives expected IDs','hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (r/'hard-train.jsonl',r/'pool-splits.json')}}
(r/'manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest))

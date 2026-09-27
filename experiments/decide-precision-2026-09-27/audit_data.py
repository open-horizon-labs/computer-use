import json,hashlib
from pathlib import Path
r=Path('/training-run/decide-precision-20260927');old=Path('/training-run/decide-binary-20260927')
read=lambda p:[json.loads(x) for x in p.read_text().splitlines()]
m=json.loads((r/'manifest.json').read_text());assert all(hashlib.sha256((r/n).read_bytes()).hexdigest()==h for n,h in m['hashes'].items())
tr=read(old/'train.jsonl');h=read(r/'hard-train.jsonl');parts=json.loads((r/'pool-splits.json').read_text())
assert len(tr)==len(h)==1500
assert all(a==b for a,b in zip(tr,h) if a['label']=='matches')
changed=sum(a['text']!=b['text'] for a,b in zip(tr,h));assert changed==41
assert all(a['label']==b['label'] for a,b in zip(tr,h))
sets=[{x['source_id'] for x in tr}]+[{x['id'] for x in rows} for rows in parts.values()]
assert not sets[0]&sets[1] and not sets[0]&sets[2] and not sets[1]&sets[2]
apps=[{x['app'] for x in tr}]+[{x['query'].split('\n')[0] for x in rows} for rows in parts.values()]
assert not apps[0]&apps[1] and not apps[0]&apps[2] and not apps[1]&apps[2]
d={'frozen_hashes_match':True,'positive_rows_identical':750,'changed_negative_texts':changed,'labels_preserved':True,'source_disjoint':True,'application_disjoint':True,'pool_task_counts':{k:len(v) for k,v in parts.items()},'max_candidates':max(len(x['candidates']) for rows in parts.values() for x in rows)}
(r/'data-audit.json').write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d))

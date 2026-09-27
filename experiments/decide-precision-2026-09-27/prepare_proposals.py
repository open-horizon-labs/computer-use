"""Reproduce proposals from training data only; approvals are in freeze_data.py."""
import json,re
from pathlib import Path
old=Path('/training-run/decide-binary-20260927')
train=[json.loads(x) for x in (old/'train.jsonl').read_text().splitlines()]; ids={x['source_id'] for x in train}
source=[json.loads(x) for x in Path('/training-run/quick-1000-data/train.jsonl').read_text().splitlines()]
proposals=[]
def words(s):return set(re.findall(r'\w+',s.lower()))
def short(s):return s.split('; parent=')[0]
for r in source:
 if r['id'] not in ids:continue
 g=r['candidates'][r['gold']]; gw=words(short(g)); opts=[]
 for i,c in enumerate(r['candidates']):
  if i==r['gold'] or short(c)==short(g):continue
  w=words(short(c));sim=len(w&gw)/max(1,len(w|gw));opts.append((sim,i,c))
 if not opts:continue
 sim,i,c=max(opts)
 proposals.append({'source_id':r['id'],'query':r['query'],'gold':g,'candidate':c,'candidate_index':i,'similarity':sim})
proposals.sort(key=lambda x:-x['similarity'])
root=Path('/training-run/decide-precision-20260927');(root/'hard-proposals.json').write_text(json.dumps(proposals,indent=2))
def name(s):
 a=re.search(r'label=([^;]*); description=([^;]*);',s)
 if not a:return ''
 return ' '.join(v for v in a.groups() if v and not v.startswith('empty-name'))
ps=[]
for r in source:
 if r['id'] not in ids:continue
 g=r['candidates'][r['gold']];gn=name(g)
 if not gn:continue
 choices=[]
 for i,c in enumerate(r['candidates']):
  cn=name(c)
  if i==r['gold'] or not cn or cn.lower()==gn.lower():continue
  score=len(words(gn)&words(cn))/max(1,len(words(gn)|words(cn)))
  if g.split(';')[0]==c.split(';')[0]:score+=.5
  choices.append((score,i,c))
 if choices:
  score,i,c=max(choices);ps.append(dict(source_id=r['id'],query=r['query'],gold=g,candidate=c,candidate_index=i,similarity=score))
ps.sort(key=lambda x:-x['similarity']);(root/'explicit-proposals.json').write_text(json.dumps(ps,indent=2))
for i,x in enumerate(ps[:70]):print(json.dumps(dict(i=i,task=x['query'].split('Task:')[-1],gold=name(x['gold']),negative=name(x['candidate']))))

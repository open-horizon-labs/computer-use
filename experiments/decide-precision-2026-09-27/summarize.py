"""Summarize frozen test outputs without changing the calibration rule."""
import json,statistics
from pathlib import Path
HERE=Path(__file__).resolve().parent
summary=json.loads((HERE/'evaluation-summary.json').read_text())
jev=json.loads((HERE/'jev-control.json').read_text())
normal=[x for x in jev['test'] if not x['target_removed']];removed=[x for x in jev['test'] if x['target_removed']]
a=[x for x in normal if x['accepted']]
summary['jev_test']={'tasks':len(normal),'accepted':len(a),'correct':sum(x['correct'] for x in a),'wrong':sum(not x['correct'] for x in a),'precision':sum(x['correct'] for x in a)/len(a) if a else None,'coverage':len(a)/len(normal),'target_removed_acceptances':sum(x['accepted'] for x in removed),'median_ms':statistics.median(x['ms'] for x in normal),'errors':sum('error' in x for x in normal+removed)}
by={x['id']:x for x in normal}
for variant in ['pilot','six','described','hard']:
 p=HERE/(variant+'-evaluation.json')
 if not p.exists():continue
 d=json.loads(p.read_text());pairs={'both_correct':0,'specialist_only':0,'jev_only':0,'neither':0}
 for r in d['splits']['test']:
  from selection import choose
  pick=None if r.get('deferred') else choose({i:x['score'] for i,x in enumerate(r['scores'])},.5,0)
  sc=pick==r['gold'] if pick is not None else False;jc=by[r['id']]['correct']
  pairs['both_correct' if sc and jc else 'specialist_only' if sc else 'jev_only' if jc else 'neither']+=1
 summary[variant]['paired_with_jev_default']=pairs
 eligible=[by[r['id']] for r in d['splits']['test'] if not r.get('deferred')]
 accepted=[r for r in eligible if r['accepted']]
 summary[variant]['jev_on_same_input_eligible_tasks']={'tasks':len(eligible),'accepted':len(accepted),'correct':sum(r['correct'] for r in accepted),'precision':sum(r['correct'] for r in accepted)/len(accepted) if accepted else None,'median_ms':statistics.median(r['ms'] for r in eligible)}
 summary[variant]['input_budget_deferrals']=sum(bool(r.get('deferred')) for r in d['splits']['test'])
 summary[variant]['median_scoring_ms']=statistics.median(r['ms'] for r in d['splits']['test'] if not r.get('deferred'))
(HERE/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))

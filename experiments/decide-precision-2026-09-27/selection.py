"""Pure full-pool selection and measurement rules; no model dependencies."""
def choose(scores,t,margin):
 if not scores:return None
 order=sorted(scores,key=lambda i:scores[i],reverse=True);best=order[0];second=scores[order[1]] if len(order)>1 else 0
 return best if scores[best]>=t and scores[best]>second and scores[best]-second>=margin else None

def metrics(rows,t,margin):
 accepted=correct=absent_errors=0
 for r in rows:
  if r.get('deferred'):continue
  scores={int(i):x['score'] for i,x in enumerate(r['scores'])};pick=choose(scores,t,margin)
  accepted+=pick is not None;correct+=pick==r['gold'] if pick is not None else 0
  scores.pop(r['gold']);absent_errors+=choose(scores,t,margin) is not None
 return dict(tasks=len(rows),accepted=accepted,correct=correct,wrong=accepted-correct,precision=correct/accepted if accepted else None,coverage=accepted/len(rows),target_removed_acceptances=absent_errors)


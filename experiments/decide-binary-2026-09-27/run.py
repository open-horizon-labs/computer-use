"""Fixed-label native ExtractorTrainer LoRA pilot; NAS inputs and output."""
import json,random,time,signal,traceback,hashlib,gc
from pathlib import Path
import torch
from gliner2 import AutoExtractor
from gliner2.training import ExtractorTrainer,TrainingConfig
from gliner2.training.data import InputExample,Classification

OUT=Path('/training-run/decide-binary-20260927');OUT.mkdir(parents=True,exist_ok=True)
BASE='fastino/GLiNER2.5-Decide';LABELS=['matches','does_not_match'];SCHEMA={'label':LABELS}
report={'base':BASE,'recipe':'native ExtractorTrainer/InputExample/Classification; no custom loss','status':'preparing'}
def save(): (OUT/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines()]
def prepare(rows,n,seed,model):
 rng=random.Random(seed);rows=list(rows);rng.shuffle(rows);chosen=[];excluded=0
 for r in rows:
  if r.get('conflicting_supervision') or r['candidates'].count(r['candidates'][r['gold']])!=1:continue
  negs=[i for i,c in enumerate(r['candidates']) if i!=r['gold'] and c!=r['candidates'][r['gold']]]
  if not negs:continue
  neg=rng.choice(negs);pairs=[]
  for i in (r['gold'],neg):
   text='Task and context:\n'+r['query']+'\nCandidate control:\n'+r['candidates'][i]
   # Audit actual schema-encoded length; no silent truncation.
   schema={'classifications':[{'task':'label','labels':LABELS,'true_label':[LABELS[int(i!=r['gold'])]]}]}
   b=model.processor._collate_batch([(text,schema)],max_len=None,error_policy='raise')
   length=b.input_ids.shape[1]
   pairs.append({'id':r['id']+':'+str(i),'source_id':r['id'],'group':r.get('group'),'app':r['query'].split('\n')[0],'text':text,'label':LABELS[int(i!=r['gold'])],'tokens':length})
  if max(x['tokens'] for x in pairs)>384:excluded+=1;continue
  chosen+=pairs
  if len(chosen)>=n:break
 assert len(chosen)>=n,(len(chosen),n)
 return chosen,excluded

def evaluate(model,data,name):
 start=time.perf_counter();pred=[];model.eval()
 with torch.inference_mode():
  for i in range(0,len(data),8):
   chunk=data[i:i+8];began=time.perf_counter();results=model.batch_classify_text([x['text'] for x in chunk],SCHEMA,batch_size=8,include_confidence=True)
   elapsed=(time.perf_counter()-began)*1000
   for row,res in zip(chunk,results):
    value=res.get('classifications',res).get('label');label=value.get('label') if isinstance(value,dict) else value
    assert label in LABELS,res
    pred.append({'id':row['id'],'gold':row['label'],'prediction':label,'correct':label==row['label'],'output':res,'batch_ms':elapsed})
 (OUT/(name+'.json')).write_text(json.dumps(pred,indent=2)+'\n')
 return {'correct':sum(x['correct'] for x in pred),'n':len(pred),'seconds':time.perf_counter()-start,'false_positive':sum(x['gold']=='does_not_match' and x['prediction']=='matches' for x in pred),'false_negative':sum(x['gold']=='matches' and x['prediction']=='does_not_match' for x in pred)}

def main():
 torch.set_num_threads(4);random.seed(42);torch.manual_seed(42)
 report['gpu']=torch.cuda.get_device_name();save()
 model=AutoExtractor.from_pretrained(BASE,local_files_only=True).to('cuda')
 train,tx=prepare(read('/training-run/quick-1000-data/train.jsonl'),1500,927,model)
 valid,vx=prepare(read('/training-run/quick-1000-data/validation.jsonl'),200,928,model)
 assert not {x['source_id'] for x in train}&{x['source_id'] for x in valid}
 assert not {x['group'] for x in train}&{x['group'] for x in valid}
 assert not {x['app'] for x in train}&{x['app'] for x in valid}
 for name,rows in [('train',train),('validation',valid)]:
  data=''.join(json.dumps(x)+'\n' for x in rows);(OUT/(name+'.jsonl')).write_text(data);report[name+'_sha256']=hashlib.sha256(data.encode()).hexdigest()
 report.update(train_n=len(train),valid_n=len(valid),excluded_long_groups={'train':tx,'validation':vx},max_encoded_tokens=max(x['tokens'] for x in train+valid),split='existing exploratory app/group-disjoint split; not a new untouched benchmark',status='baseline');save()
 report['baseline']=evaluate(model,valid,'baseline');save()
 examples=[InputExample(text=x['text'],classifications=[Classification(task='label',labels=LABELS,true_label=x['label'])]) for x in train]
 config=TrainingConfig(output_dir=str(OUT/'adapter'),num_epochs=3,batch_size=4,eval_batch_size=4,encoder_lr=1e-5,task_lr=5e-4,use_lora=True,lora_r=8,lora_alpha=16,lora_dropout=.05,lora_target_modules=['encoder','span_rep','classifier'],save_adapter_only=True,eval_strategy='no',early_stopping=False,save_best=False,num_workers=0,max_len=None,bf16=True,fp16=False,logging_steps=25,gradient_checkpointing=True,strict_training=True,skip_step_errors=False,ignore_nonfinite_losses=False)
 trainer=ExtractorTrainer(model=model,config=config)
 names=[n for n,p in trainer.model.named_parameters() if p.requires_grad];report['trainable_names']=names
 assert any('encoder' in n for n in names),'No encoder LoRA targets; recipe not realized'
 assert any('classifier' in n for n in names),'No classifier targets'
 report['trainable_parameters']=sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
 report['status']='training';save();start=time.perf_counter()
 def deadline(*args):raise TimeoutError('11-minute training budget exceeded; incomplete run is not three epochs')
 signal.signal(signal.SIGALRM,deadline);signal.alarm(660)
 try:result=trainer.train(train_data=examples)
 finally:signal.alarm(0);report['training_seconds']=time.perf_counter()-start;save()
 report['training_result']=result;report['epoch_index']=trainer.epoch;report['epochs']=trainer.epoch+1;report['steps']=trainer.global_step;save()
 report['final']=evaluate(trainer.model,valid,'final');report['train_probe']=evaluate(trainer.model,train[:128],'train-probe');report['status']='completed';save()
 print(json.dumps(report,default=str),flush=True)
if __name__=='__main__':
 try:main()
 except Exception as e:report.update(status='error',error=str(e),traceback=traceback.format_exc());save();raise

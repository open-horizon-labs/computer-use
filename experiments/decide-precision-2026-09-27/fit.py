"""Native trainer precision variants; one independent 660s fit budget each."""
import argparse,json,random,time,signal,traceback
from pathlib import Path
import torch
from gliner2 import AutoExtractor
from gliner2.training import ExtractorTrainer,TrainingConfig
from gliner2.training.data import InputExample,Classification
BASE='fastino/GLiNER2.5-Decide';LABELS=['matches','does_not_match']
DESC={'matches':'The candidate control performs the requested task on the intended object and satisfies all explicit constraints. Similar wording alone is insufficient.', 'does_not_match':'The candidate control has the wrong object, operation, state or other explicit constraint, or does not perform the requested task.'}
ROOT=Path('/training-run/decide-precision-20260927');OLD=Path('/training-run/decide-binary-20260927')
def read(p):return [json.loads(x) for x in Path(p).read_text().splitlines()]
def main():
 a=argparse.ArgumentParser();a.add_argument('variant',choices=['six','described','hard']);args=a.parse_args();out=ROOT/args.variant;out.mkdir(parents=True,exist_ok=True)
 report={'variant':args.variant,'status':'preparing','epochs_requested':6 if args.variant=='six' else 3}
 def save(): (out/'report.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
 try:
  torch.set_num_threads(4);torch.manual_seed(42);random.seed(42)
  rows=read(ROOT/'hard-train.jsonl' if args.variant=='hard' else OLD/'train.jsonl');assert len(rows)==1500
  descriptions=DESC if args.variant=='described' else None
  examples=[InputExample(text=x['text'],classifications=[Classification(task='label',labels=LABELS,true_label=x['label'],label_descriptions=descriptions)]) for x in rows]
  model=AutoExtractor.from_pretrained(BASE,local_files_only=True).to('cuda')
  schema={'classifications':[{'task':'label','labels':LABELS,'true_label':['matches'],**({'label_descriptions':descriptions} if descriptions else {})}]}
  lengths=[model.processor._collate_batch([(x['text'],schema)],max_len=None,error_policy='raise').input_ids.shape[1] for x in rows]
  report['max_encoded_tokens']=max(lengths);assert max(lengths)<=512, 'Input exceeds bounded experiment scope; no truncation'
  config=TrainingConfig(output_dir=str(out/'adapter'),num_epochs=report['epochs_requested'],batch_size=4,eval_batch_size=4,encoder_lr=1e-5,task_lr=5e-4,use_lora=True,lora_r=8,lora_alpha=16,lora_dropout=.05,lora_target_modules=['encoder','span_rep','classifier'],save_adapter_only=True,eval_strategy='no',early_stopping=False,save_best=False,num_workers=0,max_len=None,bf16=True,fp16=False,logging_steps=100,gradient_checkpointing=True,strict_training=True,skip_step_errors=False,ignore_nonfinite_losses=False)
  trainer=ExtractorTrainer(model=model,config=config)
  report.update(status='training',gpu=torch.cuda.get_device_name(),train_n=len(rows));save();start=time.perf_counter()
  def timeout(*a):raise TimeoutError('660-second fit budget exceeded')
  signal.signal(signal.SIGALRM,timeout);signal.alarm(660)
  try: result=trainer.train(train_data=examples)
  finally:signal.alarm(0);report['training_seconds']=time.perf_counter()-start;save()
  report.update(status='completed',epochs=result['total_epochs'],steps=result['total_steps'],training_result=result);save()
 except Exception as e:report.update(status='error',error=str(e),traceback=traceback.format_exc());save();raise
if __name__=='__main__':main()

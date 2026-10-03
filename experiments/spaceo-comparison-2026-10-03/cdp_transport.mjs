// Research-only transport. JSON command results stay inside the controlled fixture runner.
import readline from 'node:readline';
const ws = new WebSocket(process.argv[2]);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
let seq=0;const pending=new Map();
ws.addEventListener('message',e=>{const r=JSON.parse(e.data);if(r.id&&pending.has(r.id)){const {id,timer}=pending.get(r.id);pending.delete(r.id);clearTimeout(timer);process.stdout.write(JSON.stringify({id,...(r.error?{error:r.error}:{result:r.result})})+'\n');}});
const input=readline.createInterface({input:process.stdin});
for await(const line of input){const r=JSON.parse(line);const id=++seq;const timer=setTimeout(()=>{pending.delete(id);process.stdout.write(JSON.stringify({id:r.id,error:'deadline'})+'\n');},10000);pending.set(id,{id:r.id,timer});ws.send(JSON.stringify({id,method:r.method,params:r.params||{}}));}
ws.close();

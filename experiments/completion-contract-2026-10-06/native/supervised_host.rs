//! Research host only; private queued receipts, not a public Driver API.
use cua_driver_sdk::CuaDriver;
use serde_json::{json,Value};
use std::{collections::HashMap,io::{self,BufRead,Write},sync::{Arc,Mutex,atomic::{AtomicBool,Ordering}}};
#[link(name="CoreFoundation",kind="framework")]
unsafe extern "C" {static kCFRunLoopDefaultMode:*const std::ffi::c_void;fn CFRunLoopRunInMode(mode:*const std::ffi::c_void,seconds:f64,return_after:bool)->i32;}
async fn serve()->Result<(),Box<dyn std::error::Error>> {
 let driver=Arc::new(CuaDriver::create(None)?);let receipts:Arc<Mutex<HashMap<String,Option<Value>>>>=Arc::new(Mutex::new(HashMap::new()));let mut tasks=Vec::new();let mut counter=0;
 for line in io::stdin().lock().lines(){let req:Value=serde_json::from_str(&line?)?;let Some(id)=req.get("id") else{continue};
 let result=match req["method"].as_str().unwrap_or("") {
 "initialize"=>{let m=driver.metadata().await?;json!({"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"serverInfo":{"name":"supervised-research-host","version":m.driver_version},"_meta":{"driver_metadata":m}})},
 "tools/list"=>serde_json::from_str::<Value>(&driver.list_tools_json().await?)?,
 "tools/call"=>{let r=driver.call_tool(req["params"]["name"].as_str().ok_or("name")?.into(),req["params"]["arguments"].to_string()).await?;serde_json::from_str(&r.raw_json)?},
 "research/restore_target"=>{let pid=req["params"]["pid"].as_i64().ok_or("pid")? as i32;let window=req["params"]["window_id"].as_u64().ok_or("window")? as u32;json!({"registered":platform_macos::focus_steal::research_restore_target(pid,window),"cocoa_front_matches":platform_macos::apps::frontmost_pid()==Some(pid),"native_front_matches":platform_macos::input::skylight::front_process_matches(pid,window)})},
 "research/start"=>{counter+=1;let token=format!("receipt-{counter}");receipts.lock().unwrap().insert(token.clone(),None);let d=driver.clone();let store=receipts.clone();let key=token.clone();let name=req["params"]["name"].as_str().ok_or("name")?.to_owned();let args=req["params"]["arguments"].to_string();tasks.push(tokio::spawn(async move{let outcome=match d.call_tool(name,args).await{Ok(r)=>serde_json::from_str::<Value>(&r.raw_json).unwrap_or(json!({"isError":true})),Err(e)=>json!({"isError":true,"error":e.to_string()})};store.lock().unwrap().insert(key,Some(outcome));}));json!({"receipt":token,"status":"queued","completion_claim":false})},
 "research/poll"=>{let key=req["params"]["receipt"].as_str().ok_or("receipt")?;let store=receipts.lock().unwrap();match store.get(key){Some(Some(v))=>json!({"status":"finished","result":v}),Some(None)=>json!({"status":"pending"}),None=>json!({"status":"unknown"})}},
 "research/fence"=>{for t in tasks.drain(..){t.await?;}let watched=platform_macos::window_change_detector::research_drain().await?;json!({"receipts":*receipts.lock().unwrap(),"supervision":watched.iter().map(|c|json!({"polled":c.polled,"foreground_changed":c.foreground_changed,"new_window_count":c.new_windows.len()})).collect::<Vec<_>>()})},
 _=>json!({"error":"unsupported"})};println!("{}",json!({"jsonrpc":"2.0","id":id,"result":result}));io::stdout().flush()?;
 }
 for t in tasks{t.await?;}platform_macos::window_change_detector::research_drain().await?;driver.shutdown().await?;Ok(())
}
fn main(){if std::env::args().any(|a|a=="--deferred-supervision"){unsafe{std::env::set_var("CUA_RESEARCH_DEFER_SUPERVISION","1")};}if std::env::args().any(|a|a=="--evidence-only"){unsafe{std::env::set_var("CUA_DRIVER_WINDOW_CHANGE_TIMEOUT_MS","0")};}
 // Install Cocoa observer on main thread, then actively service its run loop.
 let _observer=platform_macos::focus_steal::FocusStealPreventer::shared();
 let done=Arc::new(AtomicBool::new(false));let flag=done.clone();let worker=std::thread::spawn(move||{let rt=tokio::runtime::Runtime::new().unwrap();let outcome=rt.block_on(serve());if let Err(e)=outcome{eprintln!("Research host error: {e}");}flag.store(true,Ordering::SeqCst);});
 while !done.load(Ordering::SeqCst){unsafe{CFRunLoopRunInMode(kCFRunLoopDefaultMode,0.01,true);}}
 worker.join().unwrap();
}

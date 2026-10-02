"""Actual Tk GUI over Xvfb/x11vnc/noVNC; HTTP is setup/scoring only."""
import json,threading,queue
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import tkinter as tk
from tkinter import ttk
commands=queue.Queue();state={'events':[]};root=tk.Tk();root.title('VNC Dispatch');root.geometry('860x560+30+30')
style=ttk.Style();style.configure('.',font=('DejaVu Sans',18));style.configure('TButton',padding=12)
frame=ttk.Frame(root,padding=30);frame.pack(fill='both',expand=True)
project=tk.StringVar(value='');quantity=tk.StringVar(value='');included=tk.BooleanVar(value=False)
def event(action):
 state['events'].append({'action':action,'project':project.get(),'quantity':quantity.get(),'included':included.get()})
def clear():
 for child in frame.winfo_children():child.destroy()
def edit():
 clear();ttk.Label(frame,text='VNC Dispatch').pack(anchor='w',pady=8)
 ttk.Label(frame,text='Project').pack(anchor='w');entry=ttk.Entry(frame,textvariable=project);entry.pack(fill='x',pady=8)
 ttk.Label(frame,text='Quantity').pack(anchor='w');ttk.Entry(frame,textvariable=quantity).pack(fill='x',pady=8)
 ttk.Checkbutton(frame,text='Include manifest',variable=included).pack(anchor='w',pady=10)
 ttk.Button(frame,text='Review dispatch',command=review).pack(anchor='w',pady=10)
def review():
 event('review');clear();ttk.Label(frame,text=f'Review {project.get()} x{quantity.get()}').pack(anchor='w',pady=18)
 ttk.Label(frame,text='Manifest included' if included.get() else 'Manifest omitted').pack(anchor='w',pady=18)
 ttk.Button(frame,text='Confirm dispatch',command=confirm).pack(anchor='w',pady=18)
def confirm():
 event('confirm');clear();ttk.Label(frame,text='Dispatch recorded').pack(anchor='w',pady=20)
def tick():
 try:
  while True:
   cmd=commands.get_nowait();state['events']=[];project.set('');quantity.set('');included.set(False);edit();cmd.set()
 except queue.Empty:pass
 root.after(30,tick)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(json.dumps(state).encode())
 def do_POST(self):
  done=threading.Event();commands.put(done);done.wait(5);self.send_response(200);self.end_headers();self.wfile.write(b'ok')
threading.Thread(target=ThreadingHTTPServer(('0.0.0.0',9101),Handler).serve_forever,daemon=True).start()
edit();tick();root.mainloop()

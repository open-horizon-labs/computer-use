"""Synthetic interactive terminal task. Only its UI reads/writes the task state."""
import json,os,sys,termios,tty
from pathlib import Path
old=termios.tcgetattr(0);selection=0;stage='menu';quantity='';events=[]
choices=['Aster','Birch','Cedar']
def save():Path(sys.argv[1]).write_text(json.dumps({'events':events,'receipt':f'{choices[selection].upper()}-{quantity}-OK'}))
def draw():
 text=['Shipment terminal','']
 if stage=='menu':
  text+=['Select a product with Up/Down, then Enter.']
  text += [('> ' if i==selection else '  ')+v for i,v in enumerate(choices)]
 elif stage=='quantity':text += [f'Product: {choices[selection]}','Quantity (digits then Enter): '+quantity]
 elif stage=='review':text += [f'Review {choices[selection]} x{quantity}','Press y to confirm; n to return.']
 else:text += [f'Receipt {choices[selection].upper()}-{quantity}-OK','Shipment complete. Press q to exit.']
 sys.stdout.write('\x1b[2J\x1b[H'+'\r\n'.join(text)+'\r\n');sys.stdout.flush()
try:
 tty.setraw(0);draw()
 while True:
  key=os.read(0,1)
  if key==b'\x1b':key+=os.read(0,2)
  if stage=='menu':
   if key in (b'\x1bOB',b'\x1b[B'):selection=min(2,selection+1)
   elif key in (b'\x1bOA',b'\x1b[A'):selection=max(0,selection-1)
   elif key==b'\r':events.append({'action':'select','product':choices[selection]});stage='quantity'
  elif stage=='quantity':
   if key.isdigit():quantity+=key.decode()
   elif key in (b'\x7f',b'\x08'):quantity=quantity[:-1]
   elif key==b'\r' and quantity:events.append({'action':'quantity','value':quantity});stage='review'
  elif stage=='review':
   if key==b'y':events.append({'action':'confirm','product':choices[selection],'quantity':quantity});stage='done';save()
   elif key==b'n':stage='menu';quantity=''
  elif key==b'q':break
  draw()
finally:termios.tcsetattr(0,termios.TCSADRAIN,old)

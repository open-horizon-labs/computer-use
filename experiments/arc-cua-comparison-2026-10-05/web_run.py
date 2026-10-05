"""Live renderer form and custom dropdown, independently scored through WKWebView.

No logins, user documents, browser profiles, display creation or raw coordinates.
Native text recovery uses foreground delivery only after independent renderer
evidence establishes that the first attempt had no effect.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from run import MCP, HERE, observe, find, act, wait_for, windows


class WebFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='oh-arc-web-')
        self.sock = Path(self.temp.name)/'web.sock'
        host = Path(os.environ['ARC_EVAL_SOURCE'])/'benchmarks/web_host.py'
        self.proc = subprocess.Popen([sys.executable,str(host),str(HERE/'web.html'),
                                     'Arc Eval Web','640','550',str(self.sock)],
                                     stdout=subprocess.DEVNULL, stderr=open('/tmp/arc-eval-web.stderr','w'))
        self.pid = self.proc.pid
        try:
            wait_for(lambda:self.sock.exists())
            wait_for(lambda:self.js('document.readyState')=='complete')
        except BaseException:
            self.close()
            raise

    def js(self, script):
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(self.sock))
            connection.sendall((json.dumps({'js':script})+'\n').encode())
            with connection.makefile('r') as stream:
                result=json.loads(stream.readline())
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result.get('value')

    def state(self):
        return self.js('({name:nameField.value,degree:__degree,submitted:__submitted,events:__events})')

    def close(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)
        self.temp.cleanup()


def trial(client, rep):
    fixture=WebFixture()
    offset=len(client.calls)
    result={'driver':client.name,'rep':rep,'case':'web_form_custom_dropdown','foreground_recovery':False}
    try:
        window=wait_for(lambda:windows(fixture.pid).get('Arc Eval Web'))
        started=time.perf_counter()
        snap=observe(client,fixture,window)
        for attempt in range(3):
            try:
                element=find(client,snap,'Full name')
                break
            except ValueError:
                if attempt==2:
                    raise
                time.sleep(.2)
                snap=observe(client,fixture,window)
        if client.name=='arc':
            response,error=act(client,fixture,window,snap,element,'TYPE_TEXT','Synthetic Person')
        else:
            response,error=client.call('type_text',pid=fixture.pid,window_id=window,
                                       element_token=element['element_token'],text='Synthetic Person')
        state=fixture.state()
        result['background_text_state']=state
        if state['name']!='Synthetic Person':
            if state['name']!='':
                raise RuntimeError('partial text observed; no blind repeat')
            if client.name=='native':
                snap=observe(client,fixture,window)
                element=find(client,snap,'Full name')
                response,error=client.call('type_text',pid=fixture.pid,window_id=window,
                    element_token=element['element_token'],text='Synthetic Person',delivery_mode='foreground')
                result['foreground_recovery']=True
            else:
                raise RuntimeError(f'arc background text did not land: {response}')
        wait_for(lambda:fixture.state()['name']=='Synthetic Person',3)
        # Fresh observations before every action; no inference from transport acknowledgment.
        for label in ('Choose degree','Master','Save application'):
            snap=observe(client,fixture,window)
            response,error=act(client,fixture,window,snap,find(client,snap,label))
            if error or (client.name=='arc' and response.get('status')!='done'):
                raise RuntimeError(str(response))
        state=wait_for(lambda:fixture.state() if fixture.state()['submitted'] else None,3)
        result['wall_ms']=(time.perf_counter()-started)*1000
        result['passed']=state['submitted']=={'name':'Synthetic Person','degree':'Master'} and any(
            e['kind']=='input' and e['value']=='Synthetic Person' for e in state['events'])
        result['state']=state
    except Exception as exc:
        result.update(passed=False,error=f'{type(exc).__name__}: {str(exc)[:350]}',state=fixture.state())
    finally:
        result['calls']=client.calls[offset:]
        result['tool_calls']=len(result['calls'])
        result['tool_ms']=sum(c['ms'] for c in result['calls'])
        if client.name=='arc':
            client.call('release',pid=fixture.pid)
        fixture.close()
    return result


def main():
    arc=MCP([sys.executable,'-m','arc_cua','mcp'],'arc-web')
    native=MCP(['cua-driver','mcp','--socket',str(Path.home()/'Library/Caches/cua-driver/cua-driver.sock')],'native-web')
    # Reuse action adapters while preserving separate private log filenames.
    arc.name='arc';native.name='native'
    output={'scope':'live WebKit renderer; independent JS oracle, scripted selections','results':[]}
    try:
        for rep in range(int(os.environ.get('ARC_EVAL_REPS','3'))):
            for client in ([arc,native] if rep%2==0 else [native,arc]):
                result=trial(client,rep)
                output['results'].append(result)
                (HERE/'web-results.json').write_text(json.dumps(output,indent=2))
                print(json.dumps({k:result.get(k) for k in ('driver','rep','passed','foreground_recovery','tool_calls','tool_ms','error')}),flush=True)
    finally:
        arc.close();native.close()


if __name__=='__main__':
    main()

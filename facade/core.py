"""Stateful local CUA facade. Driver observations own records and executable arguments."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid

DISPATCH = Path(__file__).resolve().parents[1] / 'inference/cua-decider/capability-dispatch'
sys.path.insert(0, str(DISPATCH))
from dispatch import Engine, execute_bound, request_digest
from page_candidates import NuExtractPage, filter_records
from providers import generic_from_config, RemoteSpans
from rollout import Strangler
from terminal_observation import VisualTerminal


class Gap(ValueError):
    """An observation/authority gap; must not authorize execution."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Driver:
    def __init__(self, executable=None):
        self.executable = executable or os.environ.get('CUA_DRIVER', str(Path.home()/'.local/bin/cua-driver'))

    def call(self, tool, args, timeout=20):
        result = subprocess.run([self.executable, 'call', tool, '--json', json.dumps(args)],
                                capture_output=True, text=True, timeout=timeout, check=True)
        value = json.loads(result.stdout)
        if value.get('refusal') or value.get('status') == 'refused':
            raise Gap('Driver refused: ' + str(value.get('refusal', {}).get('code', 'unknown')))
        return value

    def observe(self, pid, window_id, session):
        # resolve() avoids Driver rejecting /tmp's symlink as a nondirectory.
        with tempfile.TemporaryDirectory(prefix='cua-facade-') as directory:
            path = Path(directory).resolve()/'window.png'
            result = self.call('get_window_state', {'pid': pid, 'window_id': window_id,
                'session': session, 'max_elements': 15000, 'max_dimension': 1280,
                'screenshot_out_file': str(path)})
            result['_image'] = path.read_bytes() if path.exists() else b''
        return result


class Facade:
    def __init__(self, driver=None, generic_factory=generic_from_config, reader_factory=NuExtractPage,
                 spans_factory=RemoteSpans, visual_factory=VisualTerminal, clock=time.monotonic):
        self.driver = driver or Driver()
        self.factories = {'generic': generic_factory, 'reader': reader_factory,
                          'spans': spans_factory, 'visual': visual_factory}
        self.providers = {}
        self.clock = clock
        self.session = 'cua-facade-' + uuid.uuid4().hex[:10]
        self.started = False
        self.snapshots, self.latest, self.selections, self.readings = {}, {}, {}, {}
        self.events = []
        self.lock = threading.RLock()

    def event(self, operation, **data):
        # Content-free route audit: no screenshots, text, command payloads or secrets.
        row = {'operation': operation, **data}
        self.events.append(row)
        self.events = self.events[-200:]
        return row

    def provider(self, name):
        if name not in self.providers:
            start = self.clock()
            self.providers[name] = self.factories[name]()
            self.event('provider_start', provider=name, setup_ms=(self.clock()-start)*1000)
        return self.providers[name]

    def windows(self):
        if not self.started:
            self.driver.call('start_session', {'session': self.session})
            self.started = True
        result = self.driver.call('list_windows', {'session': self.session})
        return {'route': 'driver_inventory', 'windows': [
            {k:w[k] for k in ('app_name','pid','window_id','title','is_on_screen') if k in w}
            for w in result.get('windows', []) if w.get('title')]}

    def observe(self, pid, window_id):
        if not self.started:
            self.windows()
        began = self.clock()
        raw = self.driver.observe(pid, window_id, self.session)
        if not raw.get('snapshot_id') or raw.get('pid', pid) != pid or raw.get('window_id', window_id) != window_id:
            raise Gap('Driver did not return a bound snapshot')
        nodes = {}
        for item in raw.get('elements', []):
            index = item.get('element_index')
            if not isinstance(index, int) or index in nodes:
                raise Gap('Invalid observed element indices')
            if item.get('element_token') != f"{raw['snapshot_id']}:{index}":
                raise Gap('Element token does not belong to snapshot')
            nodes[index] = copy.deepcopy(item)
        normalized = [{k:v for k,v in item.items() if k != 'element_token'} for item in nodes.values()]
        content = {'pid': pid, 'window_id': window_id, 'title': raw.get('window_title'),
                   'bounds': raw.get('window_bounds'), 'nodes': normalized,
                   'degraded': raw.get('degraded_reason')}
        handle = 'obs_' + uuid.uuid4().hex
        image = raw.pop('_image', b'')
        state = {'raw': raw, 'nodes': nodes, 'image': image, 'fingerprint': digest(content),
                 'image_digest': hashlib.sha256(image).hexdigest() if image else None,
                 'pid': pid, 'window_id': window_id, 'created': self.clock()}
        self.snapshots[handle] = state
        self.latest[(pid, window_id)] = handle
        # Retain bounded memory. Old handles cannot become current again.
        while len(self.snapshots) > 8:
            self.snapshots.pop(next(iter(self.snapshots)))
        quality = {'ax_available': bool(nodes), 'coverage': 'observed_tree_only',
                   'terminal_text_coverage': 'unknown', 'screenshot_available': bool(image),
                   'degraded_reason': raw.get('degraded_reason'), 'progress': 'unknown'}
        self.event('observe', route='cua-driver', snapshot=handle, driver_ms=(self.clock()-began)*1000)
        return {'snapshot': handle, 'driver_snapshot_id': raw['snapshot_id'], 'title': raw.get('window_title'),
                'quality': quality, 'elements': [{'id': 'e'+str(i), 'parent_id': 'e'+str(a['parent_index']) if a.get('parent_index') in nodes else None,
                    'role': a.get('role'), 'name': a.get('label', ''), 'value': a.get('value'),
                    'enabled': a.get('enabled', True), 'actions': a.get('actions', [])} for i,a in nodes.items()]}

    def state(self, handle):
        state = self.snapshots.get(handle)
        if not state or self.latest.get((state['pid'],state['window_id'])) != handle:
            raise Gap('Stale or unknown observation; observe again')
        if self.clock() - state['created'] > 120:
            raise Gap('Observation expired; observe again')
        return state

    @staticmethod
    def node(state, candidate):
        if not isinstance(candidate,str) or not candidate.startswith('e') or not candidate[1:].isdigit():
            raise Gap('Candidate must be an observed element ID')
        try:
            return state['nodes'][int(candidate[1:])]
        except KeyError:
            raise Gap('Candidate was not observed') from None

    def subtree(self, state, candidate):
        root = self.node(state, candidate)['element_index']
        descendants = {root}
        for _ in range(len(state['nodes'])):
            more = {i for i,n in state['nodes'].items() if n.get('parent_index') in descendants}
            if more <= descendants:
                break
            descendants |= more
        text = []
        for i,n in state['nodes'].items():
            if i in descendants:
                for key in ('label','value'):
                    value = n.get(key)
                    if isinstance(value,str) and value.strip() and value not in text:
                        text.append(value)
        # Preserve explicit table cell boundaries. Container aria labels (e.g.
        # 'Cedar record') are not cell values; don't mix them into the data.
        cells = [i for i,n in state['nodes'].items()
                 if n.get('parent_index') == root and n.get('role') == 'AXCell']
        if state['nodes'][root].get('role') == 'AXRow' and cells:
            text = [json.dumps({'cells': [self.subtree(state, 'e'+str(i))[0]
                                        for i in cells]}, ensure_ascii=False)]
        return '\n'.join(text), descendants

    def read(self, snapshot, task, fields, record_ids, predicates=None, coverage_complete=False):
        state = self.state(snapshot)
        fields = copy.deepcopy(fields)
        for spec in fields.values():
            if spec.get('type') == 'string': spec['type'] = 'text'
        if not record_ids or len(set(record_ids)) != len(record_ids):
            raise Gap('Supply distinct observed record roots')
        records, memberships = [], []
        for candidate in record_ids:
            text, members = self.subtree(state,candidate)
            if any(members & previous for previous in memberships):
                raise Gap('Overlapping record roots could mix fields across records')
            if not text:
                raise Gap('Record has no observed text')
            memberships.append(members)
            records.append({'id':candidate, 'text':text})
        start = self.clock()
        extraction = self.provider('reader').extract({'snapshot_id':state['raw']['snapshot_id'],
            'task':task, 'fields':{k:v['description'] for k,v in fields.items()}, 'records':records},state['raw']['snapshot_id'])
        filtered = filter_records(extraction,fields=fields,predicates=predicates or [],
            coverage_complete=coverage_complete,current_snapshot=state['raw']['snapshot_id'])
        handle = 'read_' + uuid.uuid4().hex
        result = {'reading':handle, 'snapshot':snapshot, 'route':'nuextract3', 'extraction':extraction, 'filter':filtered}
        self.readings[handle] = copy.deepcopy(result)
        while len(self.readings)>32:self.readings.pop(next(iter(self.readings)))
        self.event('read',route='nuextract3',snapshot=snapshot,records=len(records),endpoint_ms=(self.clock()-start)*1000)
        return result

    def actions(self, state, ids, operation, text):
        if operation not in ('click','type_text'):
            raise Gap('Supported bound operations: click, type_text; use explicit raw fallback for others')
        if len(set(ids)) != len(ids):raise Gap('Duplicate candidates')
        result = []
        for candidate in ids:
            node = self.node(state,candidate)
            if node.get('enabled') is False:continue
            if operation=='click' and 'AXPress' not in node.get('actions',[]):continue
            if operation=='type_text' and node.get('role') not in ('AXTextField','AXTextArea','AXComboBox','AXSearchField'):continue
            evidence,_ = self.subtree(state,candidate)
            args={'pid':state['pid'],'window_id':state['window_id'],'session':self.session,
                  'element_token':node['element_token']}
            if operation=='type_text':
                if text is None:raise Gap('type_text requires caller text')
                args['text']=text
            result.append({'id':candidate,'name':node.get('label',''),'role':node.get('role'),
                           'operation':operation,'enabled':True,'evidence_text':evidence,
                           'description':node.get('label') or node.get('value') or node.get('role',''),
                           'arguments':args})
        return result

    def choose(self, snapshot, goal, candidate_ids=None, mode='semantic', exact_name=None, exact_role=None,
               operation='click', text=None, reading=None, fields=None, predicates=None, order_by=None,
               coverage_complete=False,record_actions=None):
        state=self.state(snapshot)
        modes={'exact','semantic','visual','spans'}
        if mode not in modes:raise Gap('Unsupported selection mode')
        ids=candidate_ids if candidate_ids is not None else ['e'+str(i) for i in state['nodes']]
        # Exact uniqueness must be checked against the entire observed scope,
        # never against a caller-supplied singleton hiding duplicate controls.
        if mode=='exact':
            if not exact_name:raise Gap('Exact mode requires an observed name, not a synthetic ID')
            ids=['e'+str(i) for i in state['nodes']]
        if reading:
            read=self.readings.get(reading)
            if not read or read['snapshot']!=snapshot:raise Gap('Reading is not bound to this observation')
            if not read['filter']['complete']:return {'status':'defer','route':'nuextract3','reason':'unknown_or_incomplete_scope'}
            retained=read['filter']['eligible_ids']
            mapped=[]
            if record_actions is not None and set(record_actions)!=set(retained):
                raise Gap('Map every eligible record, and no excluded record')
            for root in retained:
                _,members=self.subtree(state,root)
                if record_actions is not None:
                    target=record_actions[root]
                    if self.node(state,target)['element_index'] not in members:
                        raise Gap('Record action is outside its source record')
                else:
                    choices=self.actions(state,['e'+str(i) for i in state['nodes'] if i in members],operation,text)
                    if len(choices)!=1:raise Gap('Record has ambiguous controls; supply record_actions')
                    target=choices[0]['id']
                mapped.append(target)
            if candidate_ids is not None and set(candidate_ids)!=set(mapped):
                raise Gap('Selection must retain every eligible extracted candidate')
            ids=mapped
            if mode=='exact':raise Gap('Extracted choice must use semantic or spans mode')
        actions=self.actions(state,ids,operation,text)
        if mode=='semantic' and len(actions)==1 and not reading:
            self.event('choose',snapshot=snapshot,route='scope_guard',mode=mode,
                       authorized=False,reason='singleton_requires_grounded_reading')
            return {'status':'defer','route':'scope_guard',
                    'reason':'singleton_requires_grounded_reading',
                    'hint':'Offer the relevant alternatives, or use a complete filtered reading; exact mode remains available for unique controls.'}
        request={'snapshot_id':state['raw']['snapshot_id'],'kind':'semantic','operation':operation,
                 'goal':goal,'actions':actions,'observation':'\n'.join(a['description'] for a in actions)}
        if reading:request['specialist_context']=read
        if mode=='exact':
            request.update(kind='exact',target={'name':exact_name,**({'role':exact_role} if exact_role else {})})
            policy=Engine({})
        elif mode=='visual':
            if not state['image']:raise Gap('Visual choice needs a Driver screenshot')
            import base64
            request['screenshot_data_url']='data:image/png;base64,'+base64.b64encode(state['image']).decode()
            policy=Engine({'jev':self.provider('visual')})
        elif mode=='spans':
            request.update(kind='match',shape='spans',language='en',candidate_ids=[a['id'] for a in actions],
                fields=fields or {},predicates=predicates or [],order_by=order_by or [],coverage_complete=coverage_complete)
            # Lazy recovery: don't start Julia unless the dispatcher actually asks.
            policy=Strangler.from_config({'gliner2':self.provider('spans'),
                'incumbent_jev':lambda step,req:self.provider('generic')(step,req)})
        else:
            policy=Strangler.from_config({'incumbent_jev':lambda step,req:self.provider('generic')(step,req)})
        start=self.clock(); event_start=len(self.events)
        decision=policy.decide(request,request['snapshot_id'])
        elapsed=(self.clock()-start)*1000
        setup=sum(e.get('setup_ms',0) for e in self.events[event_start:])
        output=decision.get('provider_outputs',[])
        route='exact_observed_control' if mode=='exact' else [r.get('route',r.get('model','unknown')) for r in output]
        provider_models=[entry.get('model') for out in output for entry in out.get('trace',[out]) if entry.get('model')]
        self.event('choose',snapshot=snapshot,route=route,models=provider_models,mode=mode,decision_ms=max(0,elapsed-setup),provider_setup_ms=setup,wall_ms=elapsed,
                   authorized=decision.get('action_authorized',False),reason=decision.get('reason'))
        result={'status':decision['status'],'route':route,'decision':decision,'snapshot':snapshot,
                'offered_count':len(actions),'candidate_scope':'caller_subset' if candidate_ids is not None and not reading and mode!='exact' else 'observed_or_filtered_scope'}
        if decision.get('action_authorized'):
            handle='sel_'+uuid.uuid4().hex
            self.selections[handle]={'snapshot':snapshot,'request':copy.deepcopy(request),'decision':copy.deepcopy(decision),
                                     'mode':mode,'operation':operation,'text':text,'used':False}
            while len(self.selections)>32:self.selections.pop(next(iter(self.selections)))
            result.update(selection=handle,selected_id=decision['action_id'])
        return result

    def act(self, selection):
        item=self.selections.get(selection)
        if not item or item['used']:raise Gap('Unknown or already consumed selection')
        state=self.state(item['snapshot'])
        item['used']=True  # Never replay an uncertain side effect.
        fresh=self.observe(state['pid'],state['window_id'])
        current=self.state(fresh['snapshot'])
        if state['fingerprint']!=current['fingerprint']:
            raise Gap('UI changed since selection; reobserve and choose again')
        if item['mode']=='visual' and state['image_digest']!=current['image_digest']:
            raise Gap('Visual evidence changed; choose again from current screenshot')
        # Rebind only after proving the entire observed AX content/frames unchanged.
        # IDs are server-owned element indices; only Driver-issued tokens change.
        request=copy.deepcopy(item['request'])
        request['snapshot_id']=current['raw']['snapshot_id']
        for action in request['actions']:
            action['arguments']['element_token']=self.node(current,action['id'])['element_token']
        decision={**item['decision'],'snapshot_id':request['snapshot_id'],'binding_digest':request_digest(request)}
        result=execute_bound(request,decision,request['snapshot_id'],lambda tool,args:self.driver.call(tool,args))
        self.latest.pop((state['pid'],state['window_id']),None)
        self.event('act',route='cua-driver',selection=selection,revalidation='unchanged_observation',
                   original_binding=item['decision']['binding_digest'],fresh_binding=decision['binding_digest'],
                   verification='pending')
        return {'status':'delivered','driver_result':result,'requires_verification':True,
                'pid':state['pid'],'window_id':state['window_id']}

    def verify(self,pid,window_id,postcondition,mode='visual',name=None,role=None,value=None):
        began=self.clock()
        fresh=self.observe(pid,window_id);state=self.state(fresh['snapshot'])
        if mode=='exact':
            if not name:raise Gap('Exact verification requires an observed label')
            matches=[n for n in state['nodes'].values() if n.get('label')==name and (role is None or n.get('role')==role)]
            ok=any(value is None or n.get('value')==value for n in matches)
            result={'status':'satisfied' if ok else 'unknown','route':'exact_postcondition',
                    'reason':'observed_matching_element' if ok else 'absence_not_proven'}
        elif mode=='visual':
            import base64
            try:
                result=self.provider('visual').inspect({**state['raw'],
                'screenshot_data_url':'data:image/png;base64,'+base64.b64encode(state['image']).decode() if state['image'] else None},postcondition,max(0.01,20-(self.clock()-began)))
            except (ValueError, RuntimeError, TimeoutError, OSError) as error:
                result={'state':'unknown','reason':'visual_provider_failure','error_type':type(error).__name__}
            result={'status':'satisfied' if result.get('state')=='ready' else 'unknown','route':'systemone_vision','assessment':result}
        else:raise Gap('Verification mode must be exact or visual')
        self.event('verify',route=result['route'],snapshot=fresh['snapshot'],status=result['status'])
        return {**result,'snapshot':fresh['snapshot'],'independent_observation':True}

    def close(self):
        for provider in self.providers.values():
            try:provider.close()
            except Exception:self.event('cleanup',status='worker_close_failed')
        self.providers.clear()
        self.snapshots.clear();self.selections.clear();self.readings.clear();self.latest.clear()
        return {'status':'closed','trace':self.events}

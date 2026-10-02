"""Complete Driver semantic snapshots as bound evidence when native AX is unavailable.

Refs never attach to duplicate labels by position. A duplicate control is resolved in
its unique observed ancestor's scoped snapshot, with unchanged subtree evidence.
"""
from collections import Counter
import re
import dom

ROLES = {'rootwebarea':'AXWebArea','heading':'AXHeading','list':'AXList','listitem':'AXGroup',
         'generic':'AXGroup','group':'AXGroup','region':'AXGroup','statictext':'AXStaticText',
         'text':'AXStaticText','paragraph':'AXGroup','button':'AXButton','link':'AXLink',
         'textbox':'AXTextField','searchbox':'AXSearchField','combobox':'AXComboBox',
         'table':'AXTable','row':'AXRow','cell':'AXCell','columnheader':'AXColumnHeader',
         'rowheader':'AXRowHeader','status':'AXGroup','dialog':'AXDialog','alert':'AXGroup'}


def gap(reason):
    from core import Gap
    return Gap('dom_binding_unavailable: ' + reason)


def identity(raw):
    data=raw.get('_dom')
    if not data:return None
    value=data['value']
    return value['target_id'],value['tab_id'],value.get('page',{}).get('url')


def complete(value):
    snap=value.get('snapshot') or {}
    if snap.get('complete') is not True or snap.get('continuation'):
        raise gap('the semantic snapshot is incomplete; no content action can be bound')
    if any(snap.get('omitted',{}).get(k,0) for k in ('budget','offscreen','unprovable_frame')):
        raise gap('the semantic snapshot omits potential competitors')
    if not snap.get('id') or not isinstance(value.get('outline'),str):
        raise gap('the semantic snapshot lacks identity or outline')


def parse(outline):
    nodes=dom.parse_outline(outline)
    if len([line for line in outline.splitlines() if line.strip()])!=len(nodes):
        raise gap('the outline cannot be parsed completely')
    # Driver can append editable shadow nodes at a depth whose parent is absent.
    # Keep every node, but never infer ancestry across that missing parent. The
    # resulting roots cannot add evidence to a record or authorize its controls.
    depths=[n['depth'] for n in nodes]
    stack=[]
    for i,n in enumerate(nodes):
        while stack and depths[stack[-1]]>=depths[i]:stack.pop()
        parent=stack[-1] if stack and depths[stack[-1]]+1==depths[i] else None
        n['parent']=parent
        n['depth']=nodes[parent]['depth']+1 if parent is not None else 0
        stack.append(i)
    for n in nodes:
        if len(n['text'])>1:n['text'][1]=re.sub(r'\s+\[[^\]]*\]$','',n['text'][1])
    return nodes


def key(node):
    return node['role'].lower(), tuple(node['text'][:1])


def ref_key(ref):
    return str(ref.get('role') or '').lower(), (ref['name'],) if ref.get('name') else ()


def members(nodes, root):
    out=[root]
    for i in range(root+1,len(nodes)):
        parent=nodes[i]['parent']
        while parent is not None and parent!=root:parent=nodes[parent]['parent']
        if parent==root:out.append(i)
    return out


def signature(nodes, root):
    return [(n['depth']-nodes[root]['depth'],n['role'],n['text']) for n in (nodes[i] for i in members(nodes,root))]


def project(value, pid, window_id, native_title=None):
    complete(value)
    parsed=parse(value['outline'])
    if len([line for line in value['outline'].splitlines() if line.strip()])!=len(parsed):raise gap('the outline cannot be parsed completely')
    refs=list(value.get('refs') or [])+list(value.get('content_refs') or [])
    # Duplicate refs occur in separate arrays on some Driver builds: deduplicate by identity only.
    refs=list({r['ref']:r for r in refs if isinstance(r,dict) and isinstance(r.get('ref'),str)}.values())
    counts=Counter(key(n) for n in parsed)
    by_key={}
    for r in refs:by_key.setdefault(ref_key(r),[]).append(r)
    unique={i:by_key[key(n)][0] for i,n in enumerate(parsed)
            if counts[key(n)]==1 and len(by_key.get(key(n),[]))==1}
    sid='dom_'+value['snapshot']['id']
    elements=[];bindings={}
    # An explicit page root preserves the facade's existing same-record grouping.
    elements.append({'element_index':0,'role':'AXWebArea','label':value.get('page',{}).get('title') or '',
                     'element_token':sid+':0','actions':[],'enabled':True})
    action_keys={ref_key(r) for r in value.get('refs') or [] if r.get('actions') and
                 r.get('visibility') in ('in_viewport','near_viewport','offscreen')}
    for i,n in enumerate(parsed):
        role=ROLES.get(n['role'].lower(),'AXGroup')
        actionable=key(n) in action_keys
        anchor=i
        record=None
        parent=n['parent']
        while parent is not None:
            if parsed[parent]['role'].lower() in ('row','listitem'):
                record=parent;break
            parent=parsed[parent]['parent']
        while anchor not in unique and parsed[anchor]['parent'] is not None:anchor=parsed[anchor]['parent']
        bound=unique.get(anchor)
        enabled=True
        elements.append({'element_index':i+1,'parent_index':(n['parent']+1) if n['parent'] is not None else 0,
                         'role':role,'label':n['text'][0] if n['text'] else '', **({'value':n['text'][1]} if len(n['text'])>1 else {}), 'element_token':sid+':'+str(i+1),
                         'actions':['AXPress'] if actionable else [],'enabled':enabled})
        if actionable and record is not None and record not in unique:
            same=[j for j,r in enumerate(parsed) if r['role']==parsed[record]['role'] and signature(parsed,j)==signature(parsed,record)]
            if len(same)==1:bindings[i+1]={'anchor':record,'search_role':parsed[record]['role'],'key':key(n)}
        elif actionable and bound:
            bindings[i+1]={'anchor':anchor,'ref':bound['ref'],'direct':anchor==i,'key':key(n)}
    # Native table cells carry child static text; preserve that same displayed-text contract.
    # The added children are source labels, never additional actionable controls.
    for i,n in enumerate(parsed):
        if n['role'].lower() in ('cell','columnheader','rowheader') and n['text']:
            index=len(parsed)+1+i
            elements.append({'element_index':index,'parent_index':i+1,'role':'AXStaticText',
                             'label':n['text'][0],'element_token':sid+':'+str(index),'actions':[],'enabled':True})
    return {'snapshot_id':sid,'pid':pid,'window_id':window_id,
            'window_title':native_title or value.get('page',{}).get('title') or '', 'elements':elements,
            '_dom':{'value':value,'parsed':parsed,'bindings':bindings}}


def observe(f, pid, window_id):
    # Read only: never prepare/attach another profile in a look or verification.
    bound=f.driver.call('get_browser_state',{'pid':pid,'window_id':window_id,'session':f.session},timeout=dom.SEMANTIC_TIMEOUT_S)
    if bound.get('binding_quality')!='exact' or bound.get('mutation_allowed') is not True:
        raise gap('the browser target is not exactly bound and authorized')
    try:
        tab=dom._tab_of(bound,f,pid)
        if not bound.get('target_id') or tab is None:raise gap('the active tab is ambiguous')
        value=f.driver.call('get_browser_state',{'target_id':bound['target_id'],'tab_id':tab['tab_id'],
                           'snapshot_format':'semantic_v2','session':f.session},timeout=dom.SEMANTIC_TIMEOUT_S)
        if value.get('target_id')!=bound['target_id'] or value.get('tab_id')!=tab['tab_id']:
            raise gap('the semantic snapshot belongs to another tab')
        raw=project(value,pid,window_id,bound.get('native_title'))
        f.event('observe_dom',route='driver_semantic_complete')
        return raw
    except Exception as error:
        from core import Gap
        if isinstance(error,Gap):error.extra={**getattr(error,'extra',{}),'browser_binding_proven':True}
        raise


def action(f, state, action_id, operation, text=None):
    index=f.node(state,action_id)['element_index']
    data=state['raw'].get('_dom')
    binding=(data or {}).get('bindings',{}).get(index)
    if binding is None:raise gap('the control has no unique Driver ref or ancestor')
    value=data['value'];ref=binding.get('ref')
    if binding.get('search_role'):
        return search_scopes(f,data,binding,operation,text)
    if not binding['direct']:
        scoped=f.driver.call('get_browser_state',{'target_id':value['target_id'],'tab_id':value['tab_id'],
            'scope_ref':ref,'snapshot_format':'semantic_v2','session':f.session},timeout=dom.SEMANTIC_TIMEOUT_S)
        complete(scoped)
        if scoped.get('target_id')!=value['target_id'] or scoped.get('tab_id')!=value['tab_id']:
            raise gap('the scoped snapshot belongs to another tab')
        parsed=parse(scoped['outline']);anchor=binding['anchor']
        matches=[i for i,n in enumerate(parsed) if key(n)==key(data['parsed'][anchor])]
        if len(matches)!=1 or signature(parsed,matches[0])!=signature(data['parsed'],anchor):
            raise gap('the observed record changed during scoped revalidation')
        candidates=[r for r in scoped.get('refs') or [] if ref_key(r)==binding['key'] and r.get('actions')]
        if len(candidates)!=1:raise gap('the scoped control is ambiguous or missing')
        needed='click' if operation=='click' else 'type'
        if needed not in candidates[0].get('actions',[]) or candidates[0].get('visibility') not in ('in_viewport','near_viewport','offscreen'):
            raise gap('the scoped control lacks proven layout or the required action')
        ref=candidates[0]['ref']
    if binding['direct']:
        refs=[r for r in value.get('refs') or [] if r.get('ref')==ref]
        needed='click' if operation=='click' else 'type'
        if len(refs)!=1 or needed not in refs[0].get('actions',[]) or refs[0].get('visibility') not in ('in_viewport','near_viewport','offscreen'):
            raise gap('the direct control lacks proven layout or the required action')
    args={'target_id':value['target_id'],'tab_id':value['tab_id'],'ref':ref,'session':f.session}
    if operation=='click':return 'browser_click',{**args,'input_route':'dom_event'}
    if operation=='type_text':return 'browser_type',{**args,'text':text,'replace':True}
    raise gap('the operation has no bound browser route')


def search_scopes(f,data,binding,operation,text):
    """Inspect unlabeled record refs; bind by unchanged subtree, never ref order."""
    value=data['value'];role=binding['search_role'];want=signature(data['parsed'],binding['anchor'])
    candidates=[r for r in value.get('content_refs') or [] if r.get('role')==role]
    if not candidates or len(candidates)>12:raise gap('unlabeled record scope exceeds the bounded 12-record search')
    deadline=f.clock()+dom.SEMANTIC_BUDGET_S
    def call(args):
        left=deadline-f.clock()
        if left<=0:raise gap('the bounded record-scope search timed out')
        return f.driver.call('get_browser_state',args,timeout=min(dom.SEMANTIC_TIMEOUT_S,left))
    base={'target_id':value['target_id'],'tab_id':value['tab_id'],'snapshot_format':'semantic_v2','session':f.session}
    for ordinal in range(len(candidates)):
        # Enumeration is read-only. Reacquire refs after each scoped snapshot invalidates them.
        # The action is admitted only by the resulting complete same-record content match.
        if ordinal:
            fresh=call(base)
            if fresh.get('target_id')!=value['target_id'] or fresh.get('tab_id')!=value['tab_id']:raise gap('the refreshed snapshot belongs to another tab')
            complete(fresh)
            parsed=parse(fresh['outline'])
            if parsed!=data['parsed']:raise gap('the page changed during record-scope search')
            candidates=[r for r in fresh.get('content_refs') or [] if r.get('role')==role]
            if len(candidates)!=len([r for r in value.get('content_refs') or [] if r.get('role')==role]):
                raise gap('record scope changed during search')
        scoped=call({**base,'scope_ref':candidates[ordinal]['ref']})
        complete(scoped)
        if scoped.get('target_id')!=value['target_id'] or scoped.get('tab_id')!=value['tab_id']:
            raise gap('the record scope belongs to another tab')
        parsed=parse(scoped['outline'])
        matches=[i for i,n in enumerate(parsed) if n['role']==role and signature(parsed,i)==want]
        if not matches:continue
        if len(matches)!=1:raise gap('the scoped record is ambiguous')
        refs=[r for r in scoped.get('refs') or [] if ref_key(r)==binding['key'] and r.get('actions')]
        if len(refs)!=1:raise gap('the scoped control is ambiguous or missing')
        needed='click' if operation=='click' else 'type'
        if needed not in refs[0].get('actions',[]) or refs[0].get('visibility') not in ('in_viewport','near_viewport','offscreen'):
            raise gap('the scoped control lacks proven layout or the required action')
        f.event('dom_scope_search',scopes=ordinal+1,route='exact_record_subtree')
        args={'target_id':value['target_id'],'tab_id':value['tab_id'],'session':f.session,'ref':refs[0]['ref']}
        if operation=='click':return 'browser_click',{**args,'input_route':'dom_event'}
        if operation=='type_text':return 'browser_type',{**args,'text':text,'replace':True}
        raise gap('the operation has no bound browser route')
    raise gap('no Driver record scope matches the observed record')

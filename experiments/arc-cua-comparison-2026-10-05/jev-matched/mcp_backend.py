"""Evaluation-only shared AX projection; execute only public snapshot-bound MCP tools."""
import hashlib
import json
import time
from arc_cua.models import ActionKind, DesktopElement, DesktopSnapshot
from arc_cua.errors import StaleDesktopState, UnsupportedDesktopAction
from arc_cua.keyboard import parse_hotkey
from run import sanitize_result

COMMON = {ActionKind.CLICK, ActionKind.TYPE_TEXT, ActionKind.SET_VALUE,
          ActionKind.RIGHT_CLICK, ActionKind.DOUBLE_CLICK}
TEXT = {'TextField', 'TextArea', 'ComboBox', 'SearchField', 'SecureTextField'}
KEYS = {'ENTER':'return', 'ESCAPE':'escape', 'ARROW_UP':'up', 'ARROW_DOWN':'down',
        'ARROW_LEFT':'left', 'ARROW_RIGHT':'right', 'PAGE_DOWN':'pagedown', 'PAGE_UP':'pageup'}

class MCPBackend:
    def __init__(self, client, driver, pid, window):
        self.client, self.driver, self.pid, self.window = client, driver, pid, window
        self.current = None
        self.bindings = {}
        self.prepared = None
        self.used_actions = []

    def observe(self):
        tool = 'observe' if self.driver == 'arc' else 'get_window_state'
        kwargs = {'pid':self.pid, 'window_id':self.window}
        if self.driver == 'cua': kwargs['include_screenshot'] = False
        for attempt in range(3):
            raw, error = self.client.call(tool, **kwargs)
            if not error: break
            if raw.get('code') != 'target_unavailable' or attempt == 2:
                raise UnsupportedDesktopAction('Observation tool refused')
            time.sleep(.1)  # observe uncertain effects; never repeat input

        if raw.get('pid') != self.pid or raw.get('window_id') != self.window:
            raise StaleDesktopState('Observation owner mismatch')
        raw = sanitize_result(raw)
        self.bindings = {}
        rows = []
        for element in raw.get('elements', []):
            if self.driver == 'arc':
                ident = element['id']
                role = element['role']
                actions = tuple(ActionKind(a) for a in element.get('actions', []) if ActionKind(a) in COMMON)
                parent = element.get('parent_id',element.get('parent'))
                binding = {'snapshot':raw['snapshot'], 'element':ident}
            else:
                ident = 'ax_' + str(element['element_index'])
                role = element['role'].removeprefix('AX')
                offered = element.get('actions', [])
                actions = []
                if 'AXPress' in offered:
                    actions += [ActionKind.CLICK]
                if role in TEXT: actions += [ActionKind.TYPE_TEXT, ActionKind.SET_VALUE]
                if 'AXShowMenu' in offered: actions += [ActionKind.RIGHT_CLICK]
                actions = tuple(actions)
                parent = 'ax_' + str(element['parent_index']) if 'parent_index' in element else None
                token = element.get('element_token')
                if actions and not token: raise StaleDesktopState('Actionable element lacks exact token')
                binding = {'pid':self.pid, 'window_id':self.window, 'element_token':token}
            value = element.get('value')
            if role in {'CheckBox','RadioButton'} and str(value) in ('0','1'): value = int(value)
            rows.append(DesktopElement(id=ident, role=role, name=element.get('name',element.get('label','')),
                value=value, actions=actions, enabled=element.get('enabled',True), visible=element.get('visible',True),
                selected=element.get('selected'), focused=element.get('focused',False),
                expanded=element.get('expanded'), parent_id=parent, source='AX'))
            self.bindings[ident] = binding
        revision = hashlib.sha256(json.dumps([r.compact() for r in rows],sort_keys=True).encode()).hexdigest()
        self.raw = raw
        self.current = DesktopSnapshot(application=raw.get('application',raw.get('app_name','')),
            window=raw.get('window',raw.get('window_title','')),revision=revision,elements=tuple(rows),
            context={'pid':self.pid,'window_id':self.window})
        return self.current

    def is_fresh(self, snapshot, action):
        self.prepared = None
        if snapshot.context.get('pid') != self.pid or snapshot.context.get('window_id') != self.window:
            return False
        fresh = self.observe()
        if action.target_id:
            try: current = fresh.element(action.target_id)
            except KeyError: return False
            if current.semantic_guard() != action.target_guard: return False
        elif fresh.revision != snapshot.revision:
            return False
        if action.secondary_target_id: return False
        self.prepared = action
        return True

    def execute(self, snapshot, action):
        if any(action is prior for prior in self.used_actions):
            raise StaleDesktopState('Consumed action cannot be repeated')
        if self.prepared is not action and not self.is_fresh(snapshot,action):
            raise StaleDesktopState('Action lacks current prepared binding')
        self.used_actions.append(action)
        self.prepared = None  # single-use even if a tool fails
        if action.kind == ActionKind.WAIT:
            time.sleep(.1); return
        if self.driver == 'arc':
            args = {'snapshot':self.raw['snapshot'],'action':action.kind.value,'settle':True}
            if action.target_id: args['element'] = self.bindings[action.target_id]['element']
            if action.value is not None: args['value'] = action.value
            if action.key: args['key'] = action.key
            if action.hotkey: args['hotkey'] = action.hotkey
            if action.scroll_direction: args['direction'] = action.scroll_direction
            if action.click_modifier: args['modifier'] = action.click_modifier
            result,error = self.client.call('act',**args)
            if error or result.get('status') != 'done': raise UnsupportedDesktopAction('Arc action refused')
            return
        args = {'pid':self.pid,'window_id':self.window}
        if action.target_id: args.update(self.bindings[action.target_id])
        if action.kind in {ActionKind.CLICK,ActionKind.RIGHT_CLICK,ActionKind.DOUBLE_CLICK}:
            tool='click'
            if action.kind == ActionKind.RIGHT_CLICK: args['button']='right'
            if action.kind == ActionKind.DOUBLE_CLICK: args['count']=2
            if action.click_modifier:
                args['modifier']=[{'MOD':'cmd','SHIFT':'shift'}[action.click_modifier]]
                args['delivery_mode']='foreground'
        elif action.kind == ActionKind.TYPE_TEXT: tool='type_text';args['text']=str(action.value)
        elif action.kind == ActionKind.SET_VALUE: tool='set_value';args['value']=str(action.value)
        elif action.kind in {ActionKind.PRESS_KEY,ActionKind.HOTKEY}:
            tool='press_key'
            key=action.key
            if action.kind == ActionKind.HOTKEY:
                modifiers,key=parse_hotkey(action.hotkey)
                args['modifiers']=[{'MOD':'cmd','CTRL':'ctrl','ALT':'option','SHIFT':'shift'}[m] for m in modifiers]
            args['key']=KEYS.get(key,key.lower())
        elif action.kind == ActionKind.SCROLL:
            tool='scroll';args['direction']=(action.scroll_direction or 'DOWN').lower()
        else: raise UnsupportedDesktopAction('Action unsupported by evaluation adapter')
        result,error=self.client.call(tool,**args)
        if error: raise UnsupportedDesktopAction('Cua action refused')

"""MCP task intent, isolated facade state, and context-bound observation handles.

Legacy calls retain their default facade. Explicit contexts never mutate it. A
context expires after an hour idle; at most 32 are retained. No desktop cleanup
is performed on expiry: only providers/state are released.
"""
import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Task:
    facade: object
    options: dict
    touched: float
    target: dict | None = None
    handles: dict = field(default_factory=dict)


class Contexts:
    def __init__(self, factory, clock=time.monotonic, ttl=3600, limit=32):
        self.factory, self.clock, self.ttl, self.limit = factory, clock, ttl, limit
        self.tasks = {}
        self.lock = threading.RLock()

    def close(self):
        for task in self.tasks.values():
            task.facade.close()
        self.tasks.clear()

    @staticmethod
    def refused(reason):
        return {'status': 'refused', 'reason': reason, 'who': 'agent', 'delivery': 'none',
                'hint': 'Call look with context for a new task, or reuse its context_id and look_id together.',
                'untrusted_page_text': True}

    def call(self, default, tool, args, context=None, context_id=None):
        # Serialize foreground work even across contexts; state still belongs to each task.
        with self.lock:
            now = self.clock()
            for key, task in list(self.tasks.items()):
                if now - task.touched >= self.ttl:
                    task.facade.close()
                    del self.tasks[key]
            args = dict(args)
            look_id = args.get('look_id')
            owner = None
            if isinstance(look_id, str) and look_id.startswith('ctx_') and ':' in look_id:
                owner, _ = look_id.split(':', 1)
                if context_id is not None and context_id != owner:
                    return self.refused('context_look_mismatch')
                context_id = owner
            if context is not None and context_id is not None:
                return self.refused('context_conflict')
            if context is not None and look_id is not None:
                return self.refused('context_look_mismatch')
            if context_id is not None and context_id not in self.tasks:
                return self.refused('context_expired_or_unknown')
            if context is not None:
                if len(self.tasks) >= self.limit:
                    return self.refused('context_capacity')
                context_id = 'ctx_' + uuid.uuid4().hex
                active = self.factory(context)
                active.context_session = context['session']
                self.tasks[context_id] = Task(active, dict(context), now)
            if context_id is None:
                with default.lock:
                    return getattr(default, tool)(**args)
            task = self.tasks[context_id]
            task.touched = now
            if look_id is not None and owner is None:
                return self.refused('context_look_mismatch')
            saved = task.handles.get(look_id) if owner else None
            if owner and saved is None:
                return self.refused('context_look_mismatch')
            if saved:args['look_id'] = saved['raw']
            targets = ('title', 'pid', 'window_id', 'url', 'device', 'terminal')
            if not any(args.get(key) is not None for key in targets):
                if saved and saved['target']:
                    args.update(saved['target'])
                elif task.target:
                    args.update(task.target)
            with task.facade.lock:
                result = getattr(task.facade, tool)(**args)
            if result.get('status') in ('ok', 'done', 'observed', 'delivered_unverified'):
                if result.get('terminal'):
                    task.target = None if result.get('closed') else {'terminal': result['terminal']}
                elif args.get('terminal') == 'list':
                    pass  # inventory is not a target switch
                elif result.get('screen') and result['screen'].get('action_binding') is False:
                    window = result['window']
                    task.target = ({'device': window['device']} if window.get('device') else
                                   {'pid': window['pid'], 'window_id': window['window_id']})
                elif args.get('device') and args['device'] != 'list':
                    task.target = {'device': args['device']}
                else:
                    # Latest observation is authoritative even when two windows
                    # have identical titles and content hashes.
                    state = next(reversed(task.facade.snapshots.values()), None)
                    if state:
                        title = (result.get('summary') or result.get('window') or {}).get('title')
                        if title and state['raw'].get('window_title') == title:
                            task.target = {'pid': state['pid'], 'window_id': state['window_id']}
            # Only envelope handles are protocol metadata. Extracted page fields
            # may themselves be named look_id and must remain unchanged.
            envelopes = [result]
            for step in result.get('steps') or []:
                if isinstance(step, dict):
                    envelopes.extend(page for page in step.get('pages', []) if isinstance(page, dict))
            for envelope in envelopes:
                if isinstance(envelope.get('look_id'), str):
                    raw = envelope['look_id']
                    target = {'terminal': envelope['terminal']} if envelope.get('terminal') else task.target
                    matches = [value for (pid, wid, handle), value in task.facade.looks.items() if handle == raw]
                    if len(matches) == 1:
                        target = {'pid': matches[0]['pid'], 'window_id': matches[0]['window_id']}
                    handle = context_id + ':' + uuid.uuid4().hex
                    task.handles[handle] = {'raw': raw, 'target': dict(target) if target else None}
                    envelope['look_id'] = handle
                    while len(task.handles) > 32:task.handles.pop(next(iter(task.handles)))
            return {**result, 'context_id': context_id, 'context': task.options}

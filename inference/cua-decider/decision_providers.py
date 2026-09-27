"""Selection-only providers. Credentials are read at runtime, never logged."""
import json
import math
import os
import shlex
import subprocess
from functools import lru_cache
from pathlib import Path
from urllib.request import Request, urlopen

from decider_adapter import choose

INSTRUCTIONS = ('Choose the single next action that best accomplishes the supplied goal from the current observation. '
                'Consider every stated constraint and compare all candidates. Return ONLY its exact action ID, '
                'with no explanation or formatting. Use reobserve if more observation is needed, or abstain if no safe action is possible.')


@lru_cache(maxsize=4)
def secret(name):
    value = os.environ.get(name)
    if value:
        return value
    path = os.environ.get(name + '_FILE')
    if path:
        value = Path(path).read_text().strip()
        if value:
            return value
    host = os.environ.get('TYPESAFE_CONNECT_SSH' if name == 'TYPESAFE_API_KEY' else 'QWEN_SECRET_SSH')
    if host:
        if host.startswith('-'):
            raise ValueError('Invalid SSH host')
        command = ('op read ' + shlex.quote('op://Fleet/Typesafe.ai Jev API Key/credential')
                   if name == 'TYPESAFE_API_KEY' else 'cat ~/.codex/secrets/fleet-inference-key')
        try:
            value = subprocess.check_output(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, command],
                                            stderr=subprocess.DEVNULL, timeout=30, text=True).strip()
        except Exception:
            raise RuntimeError('Fleet credential read failed') from None
        if value:
            return value
    raise RuntimeError(f'Set {name} or {name}_FILE, or configure Fleet SSH credential access')


class Decider:
    def __call__(self, state, candidates):
        selected, confidence, probabilities = choose(state, candidates, instructions=state['goal'])
        return {'choice': selected, 'confidence': confidence, 'probabilities': probabilities, 'provider': 'decider-service'}


class Jev:
    def __init__(self):
        self.client = None

    def __call__(self, state, candidates):
        from typesafe_sdk import Choice, RetryPolicy, TypeSafeClient
        if self.client is None:
            self.client = TypeSafeClient(api_key=secret('TYPESAFE_API_KEY'), retry=RetryPolicy(max_retries=0), timeout=30)
        result = self.client.system_one(state=state, questions={'action': Choice(instructions=state['goal'], criteria=candidates)})
        answer = result.choices['action']
        probabilities = dict(answer.probabilities)
        values = [answer.confidence, *probabilities.values()]
        if answer.choice not in candidates or set(probabilities) != set(candidates):
            raise ValueError('Jev returned an unknown choice or incomplete distribution')
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in values):
            raise ValueError('Invalid Jev confidence/probabilities')
        # Hosted results round probabilities; confidence is a distinct field, not p(choice).
        if abs(sum(probabilities.values()) - 1) > len(candidates) * 0.0051:
            raise ValueError('Jev probabilities do not sum to one')
        return {'choice': answer.choice, 'confidence': answer.confidence, 'probabilities': probabilities, 'model': getattr(result, 'model', None)}

    def close(self):
        if self.client:
            self.client.close()


class Qwen:
    def __call__(self, state, candidates):
        mode = os.environ.get('CUA_QWEN_THINKING', 'none').strip().lower()
        if mode not in ('none', 'low', 'medium', 'xhigh'):
            raise ValueError('CUA_QWEN_THINKING must be none, low, medium, or xhigh')
        thinking = ({'chat_template_kwargs': {'enable_thinking': False}}
                    if mode == 'none' else {'reasoning_effort': mode})
        payload = {'model': os.environ.get('QWEN_MODEL', 'qwen3.8-27b-exl3-mtp'), 'temperature': 0, 'max_tokens': 2048,
                   'messages': [{'role': 'system', 'content': INSTRUCTIONS}, {'role': 'user', 'content': json.dumps({'state': state, 'candidates': candidates})}]}
        payload.update(thinking)
        request = Request(os.environ.get('QWEN_BASE_URL', 'http://192.168.1.104:8080/v1').rstrip('/') + '/chat/completions',
                          json.dumps(payload).encode(), {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + secret('QWEN_API_KEY')})
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
        item = result['choices'][0]
        selected = (item['message'].get('content') or '').strip()
        if item.get('finish_reason') != 'stop' or selected not in candidates:
            raise ValueError('Qwen did not finish with an allowed action ID')
        return {'choice': selected, 'confidence': None, 'model': payload['model'], 'usage': result.get('usage'), 'thinking_mode': mode}

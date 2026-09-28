"""One resident Julia-1 option scorer, driven over JSON Lines for optional CUA selection."""
from __future__ import annotations

import contextlib
import hashlib
import json
from pathlib import Path
import sys
import time

import torch
from julia.inference import TransformerEngine
from julia.data import sequence
from transformers import __version__ as transformers_version


WEIGHTS_SHA256 = 'df853bf7fe424420011f3d0c47a05d7341aa9eefa7fb9f203ea4aada4ad95b72'
REVISION = 'a85b127321d580d65176c89ced8273f305745d85'
MAX_LENGTH = 8192
HEAD_LENGTH = 1024


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    root = Path(sys.argv[1])
    weight_path = root / 'model.safetensors'
    actual_hash = sha256(weight_path)
    if actual_hash != WEIGHTS_SHA256:
        raise ValueError('Julia checkpoint SHA-256 does not match the pinned model card')

    began = time.perf_counter()
    # The released FastEngine's optimized ModernBERT patch currently fails on
    # the published Transformers 5.0.0 runtime. Use the same weights and the
    # repository's plain TransformerEngine for this correctness-first screen.
    with contextlib.redirect_stdout(sys.stderr):
        engine = TransformerEngine(str(root), device='cuda', max_length=MAX_LENGTH,
                                   head_length=HEAD_LENGTH)
    torch.cuda.synchronize()
    load_ms = (time.perf_counter() - began) * 1000
    ready = {
        'ready': True,
        'model': 'SupersonicLabs/Julia-1',
        'revision': REVISION,
        'weights_sha256': actual_hash,
        'load_ms': load_ms,
        'device': str(engine.device),
        'gpu': torch.cuda.get_device_name(engine.device),
        'torch': str(torch.__version__),
        'transformers': transformers_version,
        'max_length': MAX_LENGTH,
        'head_length': HEAD_LENGTH,
        'engine': 'Julia TransformerEngine (unoptimized reference path)',
    }
    print(json.dumps(ready), flush=True)

    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request['criteria'], dict) or not 2 <= len(request['criteria']) <= 20:
                raise ValueError('Julia requires 2 to 20 options; never truncate candidates')
            row = {
                'state': request['state'],
                'question': request['instructions'],
                'type': 'choice',
                'options': list(request['criteria'].values()),
            }
            encoded = sequence(engine.tokenizer, row, MAX_LENGTH, HEAD_LENGTH, strict=True)
            row['_encoded'] = encoded
            began = time.perf_counter()
            # Keep the exact typed question API semantics; score rows in one
            # resident-model call and return the model's option IDs unchanged.
            scores = engine.logits([row])[0]
            torch.cuda.synchronize()
            inference_ms = (time.perf_counter() - began) * 1000
            maximum = max(scores)
            exp_scores = [float(torch.exp(torch.tensor(score - maximum)).item()) for score in scores]
            denominator = sum(exp_scores)
            probabilities = {key: value / denominator
                             for key, value in zip(request['criteria'], exp_scores)}
            choice = max(probabilities, key=probabilities.get)
            print(json.dumps({
                'id': request['id'],
                'choice': choice,
                'probabilities': probabilities,
                'max_probability': probabilities[choice],
                'inference_ms': inference_ms,
                'encoded_tokens': len(encoded['ids']),
                'option_tokens': encoded['option_tokens'],
            }), flush=True)
        except Exception as error:
            print(json.dumps({'id': request.get('id') if isinstance(request, dict) else None,
                              'error': type(error).__name__}), flush=True)


if __name__ == '__main__':
    main()

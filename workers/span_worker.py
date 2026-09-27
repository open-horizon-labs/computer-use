"""Persistent general GLiNER2.5 span-evidence worker over JSON Lines."""
from __future__ import annotations
import contextlib
import json
import sys
import time
import torch
from gliner2 import AutoExtractor

DEFAULT_MODEL = 'fastino/gliner2.5-multi-v1'


def main():
    model_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    torch.set_num_threads(4)
    with contextlib.redirect_stdout(sys.stderr):
        model = AutoExtractor.from_pretrained(model_id, local_files_only=True).to('cuda').eval()
    print(json.dumps({'ready': True, 'model': model_id, 'role': 'generic_span_evidence'}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            texts, schemas = request['texts'], request['schemas']
            if not isinstance(texts, list) or not isinstance(schemas, list) or not texts or len(texts) != len(schemas):
                raise ValueError('equal nonempty texts and schemas required')
            began = time.perf_counter()
            with torch.inference_mode():
                results = model.batch_extract(texts, schemas, batch_size=len(texts), threshold=request.get('threshold', .25),
                                               include_confidence=True, include_spans=True)
            print(json.dumps({'results': results, 'model': model_id,
                              'inference_ms': (time.perf_counter()-began)*1000}), flush=True)
        except Exception as exc:
            print(json.dumps({'error': type(exc).__name__}), flush=True)

if __name__ == '__main__':
    main()

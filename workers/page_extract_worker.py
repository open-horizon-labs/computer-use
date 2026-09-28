"""Bounded parent-managed transport to an existing NuExtract page endpoint."""
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

for line in sys.stdin:
    row = {}
    try:
        row = json.loads(line)
        request = Request(os.environ['CUA_EXTRACT_URL'], json.dumps(row).encode(),
                          {'Content-Type': 'application/json'})
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
        print(json.dumps(result), flush=True)
    except HTTPError as error:
        print(json.dumps({'error': 'HTTPError', 'http_status': error.code}), flush=True)
    except Exception as error:
        print(json.dumps({'error': type(error).__name__}), flush=True)

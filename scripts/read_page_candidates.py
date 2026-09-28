"""Read/filter a caller-supplied fresh-snapshot record request; no UI execution."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'inference/cua-decider/capability-dispatch'))
from page_candidates import NuExtractPage,filter_records

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('request',type=Path)
parser.add_argument('--current-snapshot',required=True)
args=parser.parse_args()
request=json.loads(args.request.read_text())
extractor=NuExtractPage()
try:
    extracted=extractor.extract({**request,'fields':{k:v['description'] for k,v in request['fields'].items()}},args.current_snapshot)
    result=filter_records(extracted,fields=request['fields'],predicates=request['predicates'],
                          coverage_complete=request['coverage_complete'],current_snapshot=args.current_snapshot)
    print(json.dumps({'extraction':extracted,'filter':result}))
finally:extractor.close()

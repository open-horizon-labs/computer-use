import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('visual_worker',Path(__file__).resolve().parents[1]/'workers/visual_worker.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

class VisualWireTests(unittest.TestCase):
    def test_pixels_and_constraints_survive_without_full_ax_dump(self):
        captured=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'model':'vision-test','answers':{'assessment':{'choice':'ready','vision':True}}}).encode()
        def send(req,timeout):captured.append(json.loads(req.data));return Response()
        row={'method':'inspect','snapshot_id':'s1','image':'data:image/png;base64,pixels',
             'postcondition':'Visible result','ax_text':'x'*34445,'constraints':{'retain':'all'}}
        with patch.dict(worker.os.environ,{'CUA_SYSTEMONE_URL':'http://test.invalid'}),patch.object(worker,'urlopen',send):
            result=worker.respond(row)
        self.assertEqual(result['state'],'ready')
        self.assertEqual(captured[0]['images'],[row['image']])
        self.assertNotIn('ax_text',captured[0]['state'])
        self.assertEqual(captured[0]['state']['constraints'],row['constraints'])
        self.assertEqual(captured[0]['state']['postcondition'],row['postcondition'])
    def test_text_only_response_cannot_claim_visual_success(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'model':'text','answers':{'assessment':{'choice':'ready'}}}).encode()
        with patch.dict(worker.os.environ,{'CUA_SYSTEMONE_URL':'http://test.invalid'}),patch.object(worker,'urlopen',return_value=Response()):
            with self.assertRaises(ValueError):worker.respond({'method':'inspect','snapshot_id':'s1','image':'pixels','postcondition':'Ready'})

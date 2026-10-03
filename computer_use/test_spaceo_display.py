"""Stage adapter protocol/ownership checks using disposable Python workers only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_display import AgentDisplay
from spaceo_display import SpaceODisplay, known_owner_ids
from spaces_client import SpaceMoverUnavailable, RETAINED_OWNERS

BASE = [{'id':1,'x':0,'y':0,'width':1000,'height':800,'active':True}]
EXTRA = {'id':42,'x':-1280,'y':0,'width':1280,'height':800,'active':True}


class StageAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inventory = self.root/'inventory.json'
        self.inventory.write_text(json.dumps(BASE))
        self.worker = self.root/'worker'
        self.worker.write_text('#!'+sys.executable+'\n'+'''
import json,sys,signal,time
from pathlib import Path
p=Path(__file__).with_name('inventory.json')
if sys.argv[1:]==['--inventory']:
 print(json.dumps({'schemaVersion':1,'lifecycleState':'ready','displays':json.loads(p.read_text())}));sys.exit(0)
base=json.loads(p.read_text())
p.write_text(json.dumps(base+[{'id':42,'x':-1280,'y':0,'width':1280,'height':800,'active':True}]))
def retire(*args):
 if not Path(__file__).with_name('leak').exists():p.write_text(json.dumps(base))
 sys.exit(0)
signal.signal(signal.SIGTERM,retire)
print(json.dumps({'created':True,'active':True,'id':42}),flush=True)
while True:time.sleep(.1)
''')
        self.worker.chmod(0o700)
        self.client = SpaceODisplay(worker=self.worker, fault_path=self.root/'fault.json', owner_scan=lambda: [])
        self.addCleanup(self.recover_fake)

    def recover_fake(self):
        # Operator cleanup of disposable test workers, never real Stage owners.
        c = self.client
        if c._serve:
            if c._serve.poll() is None:c._serve.terminate()
            c._serve.wait(timeout=3)
            if c._serve.stdout:c._serve.stdout.close()
            if c._serve in RETAINED_OWNERS:RETAINED_OWNERS.remove(c._serve)
        if c._journal_fd is not None:os.close(c._journal_fd)

    def test_create_reuse_and_verified_retirement_share_durable_exclusion(self):
        self.assertEqual(self.client.ensure_agent_display(1280,800),42)
        owner = self.client._serve
        self.assertEqual(self.client.ensure_agent_display(),42)
        self.assertIs(self.client._serve,owner)
        blocked = SpaceODisplay(worker=self.worker,fault_path=self.client.fault_path,owner_scan=lambda: [])
        with self.assertRaises(SpaceMoverUnavailable):blocked.ensure_agent_display()
        self.client.stop()
        self.assertFalse(self.client.fault_path.exists())
        self.assertEqual(self.client.displays(),BASE)

    def test_owner_exit_with_online_display_retains_fault_and_refuses_new_owner(self):
        self.client.ensure_agent_display()
        (self.root/'leak').touch()
        with self.assertRaises(SpaceMoverUnavailable):self.client.stop()
        self.assertTrue(self.client.fault_path.exists())
        self.assertEqual(self.client._serve.poll(),0)
        with self.assertRaises(SpaceMoverUnavailable):self.client.ensure_agent_display()

    def test_user_topology_change_is_not_clean_retirement(self):
        self.client.ensure_agent_display()
        self.inventory.write_text(json.dumps([{**BASE[0],'width':999}]))
        self.assertFalse(self.client._retirement_verified())

    def test_inventory_rejects_boolean_identity_duplicates_nonfinite_and_bad_schema(self):
        for rows in [[{**EXTRA,'id':True}], [EXTRA,EXTRA], [{**EXTRA,'x':float('nan')}]]:
            with patch.object(self.client,'run',return_value={'schemaVersion':1,'lifecycleState':'ready','displays':rows}):
                with self.assertRaises(SpaceMoverUnavailable):self.client.displays()
        with patch.object(self.client,'run',return_value={'schemaVersion':True,'displays':BASE}):
            with self.assertRaises(SpaceMoverUnavailable):self.client.displays()

    def test_good_inventory_cannot_hide_blocked_native_circuit(self):
        for state in ['blocked','unknown',None]:
            with patch.object(self.client,'run',return_value={'schemaVersion':1,'lifecycleState':state,'displays':BASE}):
                with self.assertRaises(SpaceMoverUnavailable):self.client.ensure_agent_display()
        self.assertIsNone(self.client._serve)

    def test_dormant_foreign_owners_refuse_before_claim_or_creation(self):
        self.assertEqual(known_owner_ids('7 /old/space-mover display serve --width 1920\n8 /other/OHSpaceODisplayWorker display serve --width 1280\n9 /old/space-mover displays\n'),[7,8])
        self.client.owner_scan = lambda: [7]
        with self.assertRaisesRegex(SpaceMoverUnavailable,'other known display owners'):self.client.ensure_agent_display()
        self.assertIsNone(self.client._serve)
        self.assertFalse(self.client.fault_path.exists())

    def test_missing_worker_and_invalid_backend_never_fall_back(self):
        with patch.dict(os.environ,{'CUA_DISPLAY_BACKEND':'invalid'}):
            agent = AgentDisplay(mode='required')
            with self.assertRaisesRegex(Exception,'unknown CUA_DISPLAY_BACKEND'):agent.launch_rect()
        with patch.dict(os.environ,{'CUA_DISPLAY_BACKEND':'spaceo','CUA_SPACEO_DISPLAY_WORKER':''}):
            with self.assertRaisesRegex(Exception,'prebuilt'):AgentDisplay(mode='required').launch_rect()


if __name__=='__main__':unittest.main()

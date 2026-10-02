"""AX-free reading must not create action authority or misassociate pixels."""
import asyncio
import base64
import copy
import io
import json
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from core import Facade, Gap
from test_core import FakeDriver
from task_context import Contexts
import screen

FIX = Path(__file__).parent / 'fixtures'
PIXELS = (FIX / 'live_booking_screen.png').read_bytes()
META = json.loads((FIX / 'live_booking_screen.json').read_text())


class ScreenDriver(FakeDriver):
    def __init__(self):
        super().__init__()
        self.sent = []
        self.bound = True
        self.result = {**copy.deepcopy(META), 'screenshot_png_b64': base64.b64encode(PIXELS).decode()}
        self.native = (FIX / 'live_booking_native_screen.png').read_bytes()
        self.native_target = (1, 2)

    def observe(self, *args):
        raise AssertionError('AX must not be read')

    def call(self, tool, args, timeout=20):
        self.sent.append((tool, copy.deepcopy(args)))
        if tool == 'get_browser_state':
            if 'target_id' not in args:
                return {'binding_quality': 'exact' if self.bound else 'heuristic', 'mutation_allowed': True,
                    'target_id': META['target_id'], 'tabs': [{'tab_id': META['tab_id'], 'active': True}], 'native_title': 'Demo'}
            return copy.deepcopy(self.result)
        if tool == 'get_window_state':
            assert args['include_accessibility_tree'] is False
            Path(args['screenshot_out_file']).write_bytes(self.native)
            return {'pid': self.native_target[0], 'window_id': self.native_target[1], 'window_title': 'Demo', 'capture_id': 'cap1', 'snapshot_id': 's1'}
        return super().call(tool, args, timeout)


class ScreenTests(unittest.TestCase):
    def facade(self):
        f = Facade(driver=ScreenDriver(), sleep=lambda _: None)
        self.addCleanup(f.close)
        return f

    def test_captured_browser_pixels_without_ax_or_model_or_action_handles(self):
        f = self.facade()
        f.provider = Mock(side_effect=AssertionError('no provider'))
        out = f.look(title='Demo', screen=True)
        self.assertEqual(out['status'], 'ok', out)
        self.assertEqual(out['screen']['source'], 'browser_cdp')
        self.assertEqual((out['screen']['width'], out['screen']['height']), (1840, 857))
        self.assertFalse(out['screen']['action_binding'])
        self.assertNotIn('look_id', out)
        self.assertEqual(f.looks, {})
        self.assertEqual(f.selections, {})
        self.assertEqual(f.snapshots, {})
        self.assertNotIn('get_window_state', [t for t, _ in f.driver.sent])
        self.assertFalse(set(t for t, _ in f.driver.sent) & {'browser_prepare', 'bring_to_front', 'click', 'browser_click'})

    def test_wrong_tab_or_target_never_returns_pixels_or_falls_back(self):
        for key in ('tab_id', 'target_id'):
            f = self.facade()
            f.driver.result[key] = 'different'
            out = f.look(title='Demo', screen=True)
            self.assertEqual(out.get('reason'), 'screen_target_mismatch')
            self.assertNotIn('_screen_image', out)
            self.assertNotIn('get_window_state', [t for t, _ in f.driver.sent])

    def test_native_capture_only_and_wrong_owner_refuses(self):
        f = self.facade()
        f.driver.bound = False
        out = f.look(pid=1, window_id=2, screen=True)
        self.assertEqual(out['screen']['source'], 'native_window', out)
        self.assertEqual(out['screen']['capture_id'], 'cap1')
        f.driver.native_target = (99, 2)
        out = f.look(pid=1, window_id=2, screen=True)
        self.assertEqual(out.get('reason'), 'screen_target_mismatch')
        self.assertNotIn('_screen_image', out)

    def test_blank_corrupt_and_oversize_images_do_not_reach_model(self):
        for color in ('black', 'white', 'gray'):
            buf = io.BytesIO()
            Image.new('RGB', (40, 40), color).save(buf, format='PNG')
            with self.assertRaisesRegex(Gap, 'screen_capture_blank'):
                screen.validate_image(buf.getvalue(), 'image/png')
        for data, mime in ((b'bad', 'image/png'), (PIXELS, 'image/jpeg'), (b'', 'image/png'), (PIXELS, 'text/plain')):
            with self.assertRaises(Gap):screen.validate_image(data, mime)
        with patch.object(screen, 'MAX_PIXELS', 20):
            with self.assertRaises(Gap):screen.validate_image(PIXELS, 'image/png')
        with self.assertRaises(Gap):screen.decode_image('not base64!')

    def test_mobile_reads_image_without_elements_or_install(self):
        import mobile
        backend = Mock()
        backend.call.return_value = ({'data': base64.b64encode(PIXELS).decode(), 'mimeType': 'image/png'}, False)
        bridge = mobile.Mobile(backend=backend)
        f = self.facade()
        f._mobile = bridge
        out = f.look(device='emulator-5554', screen=True)
        self.assertEqual(out['screen']['source'], 'mobile_mcp', out)
        backend.call.assert_called_once_with('mobile_take_screenshot', {'device': 'emulator-5554', 'maxSize': 2048})
        self.assertFalse(f.driver.sent)
        self.assertEqual(bridge.installed, [])

    def test_native_transparent_corners_are_allowed_but_invisible_text_is_not(self):
        im = Image.open(io.BytesIO(PIXELS)).convert('RGBA')
        im.putpixel((0, 0), (0, 0, 0, 0))
        buf = io.BytesIO();im.save(buf, format='PNG')
        self.assertEqual(screen.validate_image(buf.getvalue(), 'image/png'), im.size)
        im.putalpha(0)
        buf = io.BytesIO();im.save(buf, format='PNG')
        with self.assertRaisesRegex(Gap, 'screen_capture_blank'):
            screen.validate_image(buf.getvalue(), 'image/png')
        # Invisible colored pixels cannot make a uniform visible image readable.
        im = Image.new('RGBA', (20, 20), (0, 0, 0, 255))
        im.putpixel((0, 0), (255, 255, 255, 0))
        buf = io.BytesIO();im.save(buf, format='PNG')
        with self.assertRaisesRegex(Gap, 'screen_capture_blank'):
            screen.validate_image(buf.getvalue(), 'image/png')

    def test_mobile_jpeg_is_supported_without_reencoding(self):
        buf = io.BytesIO()
        Image.open(io.BytesIO(PIXELS)).convert('RGB').save(buf, format='JPEG')
        self.assertEqual(screen.validate_image(buf.getvalue(), 'image/jpeg'), (1840, 857))

    def test_mobile_error_and_multiple_target_arguments_refuse(self):
        import mobile
        backend = Mock()
        backend.call.return_value = ('error with private details', True)
        f = self.facade()
        f._mobile = mobile.Mobile(backend=backend)
        out = f.look(device='emulator-5554', screen=True)
        self.assertEqual(out.get('reason'), 'screen_capture_unavailable', out)
        self.assertNotIn('private', json.dumps(out))
        for args in ({'device': 'list'}, {'title': 'Demo', 'device': 'emulator-5554'}, {'title': 'Demo', 'fields': {'a': {'description': 'a'}}}, {'title': 'Demo', 'focus': 'x'}):
            self.assertEqual(f.look(screen=True, **args)['reason'], 'bad_request')

    def test_same_pixels_fresh_capture_identity_context_target_and_no_filter_authority(self):
        f = self.facade()
        contexts = Contexts(lambda _: f)
        out = contexts.call(f, 'look', {'title': 'Demo', 'screen': True}, {'session': 'user', 'presentation': 'background'})
        repeat = contexts.call(f, 'look', {'screen': True}, context_id=out['context_id'])
        self.assertEqual(repeat['window'], out['window'])
        self.assertNotEqual(repeat['screen']['observation_id'], out['screen']['observation_id'])
        self.assertEqual(contexts.tasks[out['context_id']].target, {'pid': 1, 'window_id': 2})
        self.assertFalse(contexts.tasks[out['context_id']].handles)

    def test_mcp_returns_image_block_without_base64_in_text(self):
        import server
        f = self.facade()
        with patch.object(server, 'facade', f):
            out = server.look(title='Demo', screen=True)
            self.assertEqual([c.type for c in out.content], ['text', 'image'])
            self.assertNotIn('_screen_image', out.structuredContent)
            self.assertNotIn('iVBOR', out.content[0].text)
            self.assertEqual(base64.b64decode(out.content[1].data), PIXELS)

    def test_mobile_stdio_preserves_image_content_and_drops_mapping_text(self):
        import mobile
        backend = mobile.StdioBackend(command=[sys.executable, str(Path(__file__).parent / 'fake_mobile_mcp.py')], env=dict(os.environ))
        self.addCleanup(backend.close)
        payload, error = backend.call('mobile_take_screenshot', {'device': 'emulator-5554', 'maxSize': 2048})
        self.assertFalse(error)
        self.assertEqual(set(payload), {'data', 'mimeType'})
        self.assertEqual(base64.b64decode(payload['data']), PIXELS)

    def test_real_mcp_serialization_preserves_image(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        code = 'import server; from test_screen import ScreenDriver; server.facade.driver=ScreenDriver(); server.mcp.run()'
        async def probe():
            params = StdioServerParameters(command=sys.executable, args=['-c', code], cwd=str(Path(__file__).parent))
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    result = await session.call_tool('look', {'title': 'Demo', 'screen': True})
                    self.assertFalse(result.isError, result)
                    self.assertEqual([c.type for c in result.content], ['text', 'image'])
                    self.assertFalse(result.structuredContent['screen']['action_binding'])
                    self.assertNotIn('look_id', result.structuredContent)
                    self.assertNotIn('_screen_image', result.content[0].text)
        asyncio.run(probe())

    def test_plain_look_does_not_enter_capture_path(self):
        f = Facade(driver=FakeDriver(), sleep=lambda _: None)
        self.addCleanup(f.close)
        with patch.object(screen, 'look', side_effect=AssertionError('no image work by default')):
            self.assertEqual(f.look(title='Demo')['status'], 'ok')


if __name__ == '__main__':unittest.main()

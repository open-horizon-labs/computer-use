"""A tiny stdio MCP server that answers like mobile-mcp 1.0.6 (same tool names, same answer texts), for test_mobile.py. Offline, no device.

Configured by environment (all paths are the caller's temp files):
  FAKE_MOBILE_SCREEN     file holding the exact text mobile_list_elements_on_screen answers (the captured fixtures are such files)
  FAKE_MOBILE_LOG        every tool call received is appended as one JSON line {"tool", "args", "pid"}; also {"env": {...}} once at start
  FAKE_MOBILE_DIE_AFTER  answer N calls, then exit abruptly (as a crashed node process would) on the next one received by THIS process; 0 = the first
"""
import json
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP('mobile-mcp')
LOG = os.environ.get('FAKE_MOBILE_LOG')
DIE = os.environ.get('FAKE_MOBILE_DIE_AFTER')
seen = {'n': 0}


def note(tool, args):
    seen['n'] += 1
    if LOG:
        with open(LOG, 'a') as handle:
            handle.write(json.dumps({'tool': tool, 'args': args, 'pid': os.getpid()}) + '\n')
    if DIE is not None and seen['n'] > int(DIE):
        os._exit(1)


if LOG:
    with open(LOG, 'a') as handle:
        handle.write(json.dumps({'env': {k: os.environ.get(k) for k in ('CUA_TEST_MARK', 'MOBILEMCP_DISABLE_TELEMETRY')}, 'pid': os.getpid()}) + '\n')


@mcp.tool()
def mobile_list_available_devices() -> str:
    note('mobile_list_available_devices', {})
    return json.dumps({'devices': [{'id': 'emulator-5554', 'name': 'sdk_gphone_arm64', 'platform': 'android', 'type': 'emulator', 'version': '11', 'state': 'online', 'model': 'sdk_gphone_arm64'}]})


@mcp.tool()
def mobile_list_elements_on_screen(device: str, format: str = 'text') -> str:
    note('mobile_list_elements_on_screen', {'device': device, 'format': format})
    return open(os.environ['FAKE_MOBILE_SCREEN']).read()


@mcp.tool()
def mobile_click_on_screen_at_coordinates(device: str, x: float | None = None, y: float | None = None, ref: str | None = None) -> str:
    note('mobile_click_on_screen_at_coordinates', {'device': device, 'x': x, 'y': y, 'ref': ref})
    return 'Clicked on element %s' % ref if ref else 'Clicked on screen at coordinates: %s, %s' % (x, y)


@mcp.tool()
def mobile_type_keys(device: str, text: str, submit: bool) -> str:
    note('mobile_type_keys', {'device': device, 'text': text, 'submit': submit})
    return 'Typed text: ' + text


@mcp.tool()
def mobile_open_url(device: str, url: str) -> str:
    note('mobile_open_url', {'device': device, 'url': url})
    return 'Opened URL: ' + url


if __name__ == '__main__':
    mcp.run()

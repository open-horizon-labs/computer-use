"""noVNC in a browser tab (#56): the fallback when a desktop is only reachable as a VNC client page. The preferred route stays a computer-use
server on the remote machine (#37).

Detection is structural, never by site: the semantic_v2 outline shows exactly one canvas and no other page content, and noVNC itself is named
(a vnc.html route, or element ids/classes starting with noVNC_). The page's drawn labels come from Perception on the window capture; a press maps
the label's capture pixels to the bound tab's viewport in CSS px and goes through the Driver's browser_click (Input.dispatchMouseEvent in the exactly
bound tab: background, the exact point, no window fronting). The mapping is refused, never guessed, when the capture scale cannot be proven.
A VNC password is never typed by this module or by anything that calls it.
"""
import re
from urllib.parse import urlsplit

MARKER = re.compile(r'noVNC_', re.I)
VNC_PATH = re.compile(r'(^|/)vnc(_lite)?\.html$', re.I)
STRUCTURAL = frozenset({'rootwebarea', 'webarea', 'main', 'generic', 'group', 'none', 'document', 'canvas', 'region', 'section', 'div', 'presentation'})
PASSWORD_TEXT = re.compile(r'^(vnc\s+)?(password|passcode|credentials)\b', re.I)
PASSWORD_ID = re.compile(r'noVNC_(password_input|credentials_dlg|username_input)', re.I)
CREDENTIALS_HINT = ('A password prompt is showing. This tool never types a VNC password: nothing was typed or clicked. Ask the user to enter the password '
                    'in the page themselves (or to put it in their noVNC configuration), then call look again.')


def _gap(message):
    from core import Gap
    return Gap(message)


def detect(semantic):
    """True when the semantic_v2 read (dom.read's dict) is one canvas plus noVNC markers. Pure.

    One canvas: exactly one canvas node, and every other node is structural or itself carries a noVNC_ marker (a normal page with a canvas has
    headings, text, links or buttons beside it and is not this surface). Marker: a vnc.html route, or noVNC_ anywhere in the outline."""
    if not semantic or not semantic.get('ok'):
        return False
    outline = semantic.get('outline') or ''
    canvases, other = 0, 0
    for line in outline.split('\n'):
        match = re.match(r'^\s*-\s+([A-Za-z][\w-]*)', line)
        if not match:
            continue
        role = match.group(1).lower()
        if role == 'canvas':
            canvases += 1
        elif role not in STRUCTURAL and not MARKER.search(line):
            other += 1
    if canvases != 1 or other:
        return False
    path = urlsplit((semantic.get('page') or {}).get('url') or '').path or ''
    return bool(VNC_PATH.search(path) or MARKER.search(outline))


def password_prompt(semantic, texts):
    """A VNC credentials dialog is showing: its noVNC_ ids in the outline, or a drawn text that is a password label."""
    if PASSWORD_ID.search((semantic or {}).get('outline') or ''):
        return True
    return any(PASSWORD_TEXT.match((t or '').strip()) for t in texts)


def mapping(f, state):
    """The window-local viewport (the web area's AX frame, points) and the capture scale; Gap viewport_mapping_unavailable when either is not proven."""
    webs = f._top_web_areas(state)
    frame = state['nodes'][webs[0]].get('frame') if len(webs) == 1 else None
    frame = frame or {}
    w, h = frame.get('w', frame.get('width')), frame.get('h', frame.get('height'))
    if not isinstance(frame.get('x'), (int, float)) or not isinstance(frame.get('y'), (int, float)) or not w or not h or w <= 0 or h <= 0:
        raise _gap('viewport_mapping_unavailable: the page area has no usable frame, so a drawn label cannot be placed in the tab viewport; nothing was clicked')
    scale = f._pixel_scale(state)
    if not scale:
        raise _gap('viewport_mapping_unavailable: the capture scale against the window is not provable (missing screenshot or window size, or a non-uniform ratio), so a drawn label cannot be placed in the tab viewport; nothing was clicked')
    return {'x': frame['x'], 'y': frame['y'], 'w': w, 'h': h, 'sx': scale[0], 'sy': scale[1]}


def css_point(view, bounds):
    """Centre of a region (capture px) in viewport CSS px: px / scale = window points, minus the viewport origin (1 CSS px = 1 point at 100% page zoom).
    A point outside the viewport is refused."""
    cx = (bounds.get('x', 0) + bounds.get('width', 0) / 2) / view['sx'] - view['x']
    cy = (bounds.get('y', 0) + bounds.get('height', 0) / 2) / view['sy'] - view['y']
    if not (0 <= cx <= view['w'] and 0 <= cy <= view['h']):
        raise _gap('viewport_mapping_unavailable: the label maps outside the tab viewport (%.0f, %.0f of %.0f x %.0f); nothing was clicked' % (cx, cy, view['w'], view['h']))
    return round(cx, 2), round(cy, 2)


def surface(f, pid, window_id, state):
    """For do: None when this window is not a noVNC tab, else {'semantic', 'target_id', 'tab_id', 'view'} with the EXACT bound tab. Raises Gap on a refused bind or mapping."""
    import browser
    import dom
    semantic = dom.read(f, pid, window_id)
    if not detect(semantic):
        return None
    view = mapping(f, state)
    target, tab = browser.bind(f, pid, window_id)
    return {'semantic': semantic, 'target_id': target, 'tab_id': tab, 'view': view}

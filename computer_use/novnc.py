"""noVNC in a browser tab (#56): the fallback when a desktop is only reachable as a VNC client page. The preferred route stays a computer-use
server on the remote machine (#37).

Detection is structural, never by site: the semantic_v2 outline shows exactly one canvas and no page content beside noVNC's own client chrome (its
toolbar buttons, status text and hidden input), and noVNC itself is named (a vnc.html route, a noVNC_ id/class, or the client's own "no VNC" heading). The page's drawn labels come from Perception on the window capture; a press maps
the label's capture pixels to the bound tab's viewport in CSS px and goes through the Driver's browser_click (Input.dispatchMouseEvent in the exactly
bound tab: background, the exact point, no window fronting). The mapping is refused, never guessed, when the capture scale cannot be proven.
A VNC password is never typed by this module or by anything that calls it.
"""
import re
from urllib.parse import urlsplit

MARKER = re.compile(r'noVNC_', re.I)
VNC_PATH = re.compile(r'(^|/)vnc(_lite)?\.html$', re.I)
STRUCTURAL = frozenset({'rootwebarea', 'webarea', 'main', 'generic', 'group', 'none', 'document', 'canvas', 'region', 'section', 'div', 'presentation'})
# Live (noVNC 1.x vnc.html, measured 2026-10-01): beside the canvas the outline holds the client's own heading "no VNC", toolbar buttons (Extra keys,
# Clipboard, Fullscreen, Settings, Disconnect), a hidden keyboard textarea, an image and static text. Those are the client chrome, never page content.
CLIENT_CHROME = frozenset({'button', 'textbox', 'textarea', 'image', 'img', 'statictext', 'text', 'linebreak', 'checkbox', 'combobox', 'listbox', 'option', 'slider',
                           'spinbutton', 'label', 'labeltext', 'radio', 'radiobutton', 'switch', 'separator', 'dialog', 'form', 'list', 'listitem', 'status', 'alert'})
# The credentials dialog is page DOM, not canvas (live: form > list > listitem > labeltext "Password:" + textbox, and the button "Send Credentials"), shown
# while the canvas is still "Connecting...".
PASSWORD_OUTLINE = re.compile(r'^\s*-\s+(?:statictext|labeltext|label|text|button|heading|textbox|generic)\s+"?\s*(?:vnc\s+)?(?:password|username|passcode|credentials|send credentials)\b', re.I | re.M)
HEADING = re.compile(r'^\s*-\s+heading\s+"([^"]*)"', re.I)
CLIENT_HEADING = re.compile(r'^no\s?vnc$', re.I)
PASSWORD_TEXT = re.compile(r'^(vnc\s+)?(password|passcode|credentials)\b', re.I)
PASSWORD_ID = re.compile(r'noVNC_(password_input|credentials_dlg|username_input)', re.I)
CREDENTIALS_HINT = ('A password prompt is showing. This tool never types a VNC password: nothing was typed or clicked. Ask the user to enter the password '
                    'in the page themselves (or to put it in their noVNC configuration), then call look again.')


def _gap(message):
    from core import Gap
    return Gap(message)


def detect(semantic):
    """True when the semantic_v2 read (dom.read's dict) is one canvas plus the noVNC client and a noVNC marker. Pure.

    One canvas: exactly one canvas node, and every other node is structural, noVNC client chrome (CLIENT_CHROME roles, the client's own "no VNC"
    heading) or itself carries a noVNC_ marker; a normal page with a canvas has other headings, links, tables or text blocks beside it and is not this
    surface. Marker: a vnc.html route, noVNC_ anywhere in the outline, or the client's "no VNC" heading."""
    if not semantic or not semantic.get('ok'):
        return False
    outline = semantic.get('outline') or ''
    canvases, other, client_heading = 0, 0, False
    for line in outline.split('\n'):
        match = re.match(r'^\s*-\s+([A-Za-z][\w-]*)', line)
        if not match:
            continue
        role = match.group(1).lower()
        if role == 'canvas':
            canvases += 1
        elif role == 'heading':
            name = HEADING.match(line)
            if name and CLIENT_HEADING.match(name.group(1).strip()):
                client_heading = True
            elif not MARKER.search(line):
                other += 1
        elif role not in STRUCTURAL and role not in CLIENT_CHROME and not MARKER.search(line):
            other += 1
    if canvases != 1 or other:
        return False
    path = urlsplit((semantic.get('page') or {}).get('url') or '').path or ''
    return bool(VNC_PATH.search(path) or MARKER.search(outline) or client_heading)


def password_prompt(semantic, texts):
    """A VNC credentials dialog is showing: its noVNC_ ids in the outline, or a drawn text that is a password label."""
    outline = (semantic or {}).get('outline') or ''
    if PASSWORD_ID.search(outline) or PASSWORD_OUTLINE.search(outline):
        return True
    return any(PASSWORD_TEXT.match((t or '').strip()) for t in texts)


def mapping(f, state):
    """The web area's placement in the capture and the capture scale: {'ox', 'oy' (capture px of the viewport's top-left), 'kx', 'ky' (capture px per CSS
    px), 'w', 'h' (viewport CSS px)}. Gap viewport_mapping_unavailable when either is not proven.

    Live (Driver 0.30.x, Chrome on macOS, 2026-10-01): an element's `frame` is SCREEN-absolute (the web area's x equals the window's x, negative on a
    second display) and `screenshot_frame` is the same box in capture pixels. So the viewport origin is the web area's screenshot_frame and the scale is
    its capture size over its frame size; the PNG against the window size must agree with it, or nothing is mapped. Without a screenshot_frame the origin
    is the frame minus the window bounds origin, scaled by the PNG against the window size. 1 CSS px = 1 point (100% page zoom) is assumed."""
    webs = f._top_web_areas(state)
    node = state['nodes'][webs[0]] if len(webs) == 1 else {}
    frame = node.get('frame') or {}
    w, h = frame.get('w', frame.get('width')), frame.get('h', frame.get('height'))
    if not _num(frame.get('x')) or not _num(frame.get('y')) or not _num(w) or not _num(h) or w <= 0 or h <= 0:
        raise _gap('viewport_mapping_unavailable: the page area has no usable frame, so a drawn label cannot be placed in the tab viewport; nothing was clicked')
    scale = f._pixel_scale(state)
    if not scale:
        raise _gap('viewport_mapping_unavailable: the capture scale against the window is not provable (missing screenshot or window size, or a non-uniform ratio), so a drawn label cannot be placed in the tab viewport; nothing was clicked')
    sf = node.get('screenshot_frame') or {}
    sw, sh = sf.get('w', sf.get('width')), sf.get('h', sf.get('height'))
    if _num(sf.get('x')) and _num(sf.get('y')) and _num(sw) and _num(sh) and sw > 0 and sh > 0 and state['raw'].get('screenshot_frame_valid') is not False:
        kx, ky = sw / w, sh / h
        if abs(kx - scale[0]) > 0.02 * max(kx, scale[0]) or abs(ky - scale[1]) > 0.02 * max(ky, scale[1]):
            raise _gap('viewport_mapping_unavailable: the page area and the capture disagree on the scale (%.3f/%.3f against %.3f/%.3f), so a drawn label cannot be placed in the tab viewport; nothing was clicked' % (kx, ky, scale[0], scale[1]))
        return {'ox': sf['x'], 'oy': sf['y'], 'kx': kx, 'ky': ky, 'w': w, 'h': h}
    origin = state['raw'].get('window_bounds') or {}
    if not _num(origin.get('x')) or not _num(origin.get('y')):
        raise _gap('viewport_mapping_unavailable: neither the page area\'s capture frame nor the window origin is known, so a drawn label cannot be placed in the tab viewport; nothing was clicked')
    return {'ox': (frame['x'] - origin['x']) * scale[0], 'oy': (frame['y'] - origin['y']) * scale[1], 'kx': scale[0], 'ky': scale[1], 'w': w, 'h': h}


def _num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def css_point(view, bounds):
    """Centre of a region (capture px) in viewport CSS px: (px - the viewport origin in the capture) / capture px per CSS px. A point outside the viewport is refused."""
    cx = (bounds.get('x', 0) + bounds.get('width', 0) / 2 - view['ox']) / view['kx']
    cy = (bounds.get('y', 0) + bounds.get('height', 0) / 2 - view['oy']) / view['ky']
    if not (0 <= cx <= view['w'] and 0 <= cy <= view['h']):
        raise _gap('viewport_mapping_unavailable: the label maps outside the tab viewport (%.0f, %.0f of %.0f x %.0f); nothing was clicked' % (cx, cy, view['w'], view['h']))
    return round(cx, 2), round(cy, 2)


def in_viewport(view, regions):
    """The regions whose centre is inside the tab viewport. The capture is the whole window, so the tab strip, address bar and toolbar are drawn text too,
    and none of it is the remote desktop."""
    kept = []
    for r in regions:
        try:
            css_point(view, r['bounds'])
        except Exception:
            continue
        kept.append(r)
    return kept


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

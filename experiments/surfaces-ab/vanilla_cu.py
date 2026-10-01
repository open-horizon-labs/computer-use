"""The "vanilla" arm's tool: a tiny local MCP server exposing ONE tool, `computer`, with the Anthropic API computer tool's action set and
parameter names (screenshot in, coordinates and keys out; no accessibility tree, no DOM, no Cua Driver). It acts on the user's REAL
main screen with real HID input, so run it only inside the A/B harness with the user's consent (README.md).

Why our own executor: Claude Code's built-in computer use cannot run under `claude -p` and there is no API key for the API tool, so this
implements the same contract: screenshots of the main display scaled to fit 1280x800 (aspect kept), coordinates in that scaled space
mapped back to screen points, every action except `screenshot` and `cursor_position` returning a fresh screenshot after a short settle.

macOS permissions for the process that runs this (the terminal / claude): Screen Recording (screencapture) and Accessibility (posting events).
Run with the facade venv: /Users/muness1/src/open-horizon-labs/computer-use/.venv-facade/bin/python vanilla_cu.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get('CUA_CACHE_DIR') or Path.home() / '.cache' / 'computer-use') / 'surfaces-ab'
MAX_W, MAX_H = 1280, 800
SETTLE_S = float(os.environ.get('VANILLA_SETTLE_S', '1.0'))
ACTIONS = ('screenshot', 'left_click', 'right_click', 'double_click', 'middle_click', 'mouse_move', 'left_click_drag', 'type', 'key',
           'scroll', 'wait', 'cursor_position')
CLICKS = {'left_click': ('left', 1), 'right_click': ('right', 1), 'double_click': ('left', 2), 'middle_click': ('middle', 1)}
NEEDS_COORDINATE = ('left_click', 'right_click', 'double_click', 'middle_click', 'mouse_move', 'left_click_drag', 'scroll')
DIRECTIONS = ('up', 'down', 'left', 'right')
MAX_WAIT_S = 100

# --- geometry -------------------------------------------------------------------------------------------------------------

def scaled_size(pixels_w, pixels_h):
    """The size the model sees: the display (in pixels) scaled down to fit MAX_W x MAX_H, aspect kept, never enlarged."""
    scale = min(MAX_W / pixels_w, MAX_H / pixels_h, 1.0)
    return max(1, round(pixels_w * scale)), max(1, round(pixels_h * scale))


def to_points(x, y, scaled, points, origin=(0, 0)):
    """Scaled screenshot coordinates -> screen points (the CoreGraphics global space the HID events use)."""
    return (origin[0] + x * points[0] / scaled[0], origin[1] + y * points[1] / scaled[1])


def to_scaled(px, py, scaled, points, origin=(0, 0)):
    return (round((px - origin[0]) * scaled[0] / points[0]), round((py - origin[1]) * scaled[1] / points[1]))


# --- keys -----------------------------------------------------------------------------------------------------------------
FLAG = {'shift': 0x20000, 'ctrl': 0x40000, 'alt': 0x80000, 'cmd': 0x100000, 'fn': 0x800000}
MODIFIERS = {'ctrl': 'ctrl', 'control': 'ctrl', 'control_l': 'ctrl', 'control_r': 'ctrl', 'shift': 'shift', 'shift_l': 'shift', 'shift_r': 'shift',
             'alt': 'alt', 'option': 'alt', 'opt': 'alt', 'alt_l': 'alt', 'alt_r': 'alt', 'cmd': 'cmd', 'command': 'cmd', 'meta': 'cmd',
             'super': 'cmd', 'super_l': 'cmd', 'super_r': 'cmd', 'win': 'cmd', 'fn': 'fn'}
_LETTERS = dict(zip('asdfhgzxcvbqweryt', (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17)))
_LETTERS.update(dict(zip('oui', (31, 32, 34))))
_LETTERS.update({'p': 35, 'l': 37, 'j': 38, 'k': 40, 'n': 45, 'm': 46})
_DIGITS = {'1': 18, '2': 19, '3': 20, '4': 21, '6': 22, '5': 23, '9': 25, '7': 26, '8': 28, '0': 29}
_PUNCT = {'=': 24, '-': 27, ']': 30, '[': 33, "'": 39, ';': 41, '\\': 42, ',': 43, '/': 44, '.': 47, '`': 50}
NAMED = {'return': 36, 'enter': 36, 'kp_enter': 36, 'tab': 48, 'space': 49, 'backspace': 51, 'escape': 53, 'esc': 53, 'delete': 117,
         'home': 115, 'end': 119, 'page_up': 116, 'prior': 116, 'pageup': 116, 'page_down': 121, 'next': 121, 'pagedown': 121,
         'left': 123, 'right': 124, 'down': 125, 'up': 126,
         'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118, 'f5': 96, 'f6': 97, 'f7': 98, 'f8': 100, 'f9': 101, 'f10': 109, 'f11': 103, 'f12': 111,
         'minus': 27, 'equal': 24, 'comma': 43, 'period': 47, 'slash': 44, 'backslash': 42, 'semicolon': 41, 'apostrophe': 39,
         'grave': 50, 'bracketleft': 33, 'bracketright': 30}
KEYCODES = {**_LETTERS, **_DIGITS, **_PUNCT, **NAMED}
SHIFTED = {'+': '=', '_': '-', '?': '/', ':': ';', '"': "'", '<': ',', '>': '.', '{': '[', '}': ']', '|': '\\', '~': '`',
           '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0'}


def parse_key(text):
    """xdotool-style key text -> [(keycode, flags_mask), ...]. 'cmd+l' is one chord, 'Return' one key, 'cmd+a Delete' two chords in order.
    Raises ValueError for an unknown key or a chord with no key."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('key needs text, e.g. "Return" or "cmd+l"')
    chords = []
    for chord in text.split():
        parts = chord.split('+') if chord != '+' else ['plus']
        flags, code = 0, None
        for i, part in enumerate(parts):
            low = part.lower()
            if low in MODIFIERS and i < len(parts) - 1:
                flags |= FLAG[MODIFIERS[low]]
                continue
            if code is not None:
                raise ValueError('more than one non-modifier key in %r' % chord)
            if low == 'plus':
                code, flags = KEYCODES['equal'], flags | FLAG['shift']
            elif part in SHIFTED:
                code, flags = KEYCODES[SHIFTED[part]], flags | FLAG['shift']
            elif len(part) == 1 and part.isalpha() and part.isupper():
                code, flags = KEYCODES[low], flags | FLAG['shift']
            elif low in KEYCODES:
                code = KEYCODES[low]
            else:
                raise ValueError('unknown key %r in %r' % (part, chord))
        if code is None:
            raise ValueError('no key in %r (only modifiers)' % chord)
        chords.append((code, flags))
    return chords


# --- argument validation --------------------------------------------------------------------------------------------------

def _pair(name, value, size):
    if not (isinstance(value, (list, tuple)) and len(value) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        raise ValueError('%s must be [x, y] in the screenshot coordinate space' % name)
    x, y = value
    if not (0 <= x < size[0] and 0 <= y < size[1]):
        raise ValueError('%s %s is outside the %dx%d screenshot' % (name, list(value), size[0], size[1]))
    return x, y


def validate(action, size, coordinate=None, start_coordinate=None, text=None, scroll_direction=None, scroll_amount=None, duration=None):
    """Checks one call against the API tool's contract; returns the normalized arguments. ValueError names the problem."""
    if action not in ACTIONS:
        raise ValueError('unknown action %r; use one of: %s' % (action, ', '.join(ACTIONS)))
    out = {'action': action}
    if action in NEEDS_COORDINATE:
        if coordinate is None:
            raise ValueError('%s requires coordinate [x, y]' % action)
        out['coordinate'] = _pair('coordinate', coordinate, size)
    if action == 'left_click_drag':
        if start_coordinate is None:
            raise ValueError('left_click_drag requires start_coordinate [x, y]')
        out['start_coordinate'] = _pair('start_coordinate', start_coordinate, size)
    if action == 'type':
        if not isinstance(text, str) or text == '':
            raise ValueError('type requires text')
        out['text'] = text
    if action == 'key':
        out['keys'] = parse_key(text)
    if action == 'scroll':
        if scroll_direction not in DIRECTIONS:
            raise ValueError('scroll requires scroll_direction: one of %s' % ', '.join(DIRECTIONS))
        amount = 3 if scroll_amount is None else scroll_amount
        if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= 50:
            raise ValueError('scroll_amount must be an integer from 1 to 50')
        out['scroll_direction'], out['scroll_amount'] = scroll_direction, amount
    if action == 'wait':
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 <= duration <= MAX_WAIT_S:
            raise ValueError('wait requires duration in seconds, 0 to %d' % MAX_WAIT_S)
        out['duration'] = duration
    return out


# --- executor -------------------------------------------------------------------------------------------------------------

class Display:
    def __init__(self, x, y, points_w, points_h, pixels_w, pixels_h, post_event=True, screen_capture=True):
        self.origin, self.points, self.pixels = (x, y), (points_w, points_h), (pixels_w, pixels_h)
        self.scaled = scaled_size(pixels_w, pixels_h)
        self.post_event, self.screen_capture = post_event, screen_capture

    @classmethod
    def from_info(cls, info):
        return cls(info['x'], info['y'], info['points_w'], info['points_h'], info['pixels_w'], info['pixels_h'],
                   info.get('post_event', True), info.get('screen_capture', True))

    def rect(self):
        return {'x': self.origin[0], 'y': self.origin[1], 'width': self.points[0], 'height': self.points[1]}


def helper_path():
    """cuinput, compiled on demand like the sampler (cached under ~/.cache/computer-use/surfaces-ab/, rebuilt when the source is newer)."""
    source, binary = HERE / 'cuinput.swift', CACHE / 'cuinput'
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(['swiftc', '-O', str(source), '-o', str(binary)], check=True, capture_output=True)
    return str(binary)


class Executor:
    """Real screen: screencapture for sight, cuinput for hands. Tests substitute a fake with the same methods."""

    def __init__(self, display=None, run=None, settle=SETTLE_S):
        self._run = run or self._run_helper
        self.display = display or Display.from_info(self.info())
        self.settle = settle

    def _run_helper(self, args, stdin=None):
        done = subprocess.run([helper_path()] + [str(a) for a in args], input=stdin, capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            raise RuntimeError('input helper failed (%s): %s' % (' '.join(map(str, args[:1])), done.stderr.strip()))
        return done.stdout

    def info(self):
        return json.loads(self._run(['info']))

    def screenshot(self):
        """PNG bytes of the main display scaled to display.scaled."""
        d = self.display
        with tempfile.TemporaryDirectory(prefix='vanilla-cu-') as tmp:
            raw, out = Path(tmp) / 'raw.png', Path(tmp) / 'scaled.png'
            subprocess.run(['screencapture', '-x', '-C', '-m', '-t', 'png', str(raw)], check=True, timeout=30)
            if not raw.exists() or raw.stat().st_size == 0:
                raise RuntimeError('screencapture produced no image (Screen Recording permission?)')
            if d.scaled == d.pixels:
                return raw.read_bytes()
            subprocess.run(['sips', '-z', str(d.scaled[1]), str(d.scaled[0]), str(raw), '--out', str(out)], check=True, capture_output=True, timeout=30)
            return out.read_bytes()

    def point(self, xy):
        return to_points(xy[0], xy[1], self.display.scaled, self.display.points, self.display.origin)

    def perform(self, a):
        """Posts the action's events. Returns text for actions that answer in text, else None."""
        act = a['action']
        if act in CLICKS:
            button, count = CLICKS[act]
            x, y = self.point(a['coordinate'])
            self._run(['click', '%.1f' % x, '%.1f' % y, button, count])
        elif act == 'mouse_move':
            x, y = self.point(a['coordinate'])
            self._run(['move', '%.1f' % x, '%.1f' % y])
        elif act == 'left_click_drag':
            (x1, y1), (x2, y2) = self.point(a['start_coordinate']), self.point(a['coordinate'])
            self._run(['drag', '%.1f' % x1, '%.1f' % y1, '%.1f' % x2, '%.1f' % y2])
        elif act == 'type':
            self._run(['type'], stdin=a['text'])
        elif act == 'key':
            for code, flags in a['keys']:
                self._run(['key', code, flags])
        elif act == 'scroll':
            x, y = self.point(a['coordinate'])
            n = a['scroll_amount']
            dx, dy = {'up': (0, n), 'down': (0, -n), 'left': (n, 0), 'right': (-n, 0)}[a['scroll_direction']]
            self._run(['scroll', '%.1f' % x, '%.1f' % y, dx, dy])
        elif act == 'wait':
            time.sleep(a['duration'])
        elif act == 'cursor_position':
            px, py = map(float, self._run(['pos']).split())
            sx, sy = to_scaled(px, py, self.display.scaled, self.display.points, self.display.origin)
            return 'X=%d,Y=%d' % (sx, sy)
        return None


def describe(display):
    w, h = display.scaled
    return ('Use a mouse and keyboard to interact with a computer, and take screenshots.\n'
            '* This is an interface to the user\'s REAL desktop: you control the actual screen, mouse and keyboard.\n'
            '* You only see the screen through screenshots; there is no other view of it. Take a screenshot to see the current state of the screen.\n'
            '* The screen\'s resolution is %dx%d (display_width_px=%d, display_height_px=%d). All coordinates are in this space, origin top-left.\n'
            '* Whenever you intend to move the cursor to click on an element like an icon, consult a screenshot to determine the coordinates of the element before moving the cursor.\n'
            '* If a click did not seem to take effect, adjust the coordinates and try again, using zoom-in style care for small targets.\n'
            '* Every action except screenshot and cursor_position returns a fresh screenshot taken just after the action.\n'
            '* Actions: screenshot; left_click, right_click, double_click, middle_click (coordinate [x, y]); mouse_move (coordinate); '
            'left_click_drag (start_coordinate, coordinate); type (text); key (text: xdotool-style key or chord, e.g. "Return", "cmd+l"); '
            'scroll (coordinate, scroll_direction up/down/left/right, scroll_amount); wait (duration in seconds); cursor_position.' % (w, h, w, h))


def build_server(executor):
    from mcp.server.fastmcp import FastMCP, Image
    mcp = FastMCP('vanilla-cu')

    @mcp.tool(name='computer', description=describe(executor.display))
    def computer(action: str, coordinate: list[int] | None = None, start_coordinate: list[int] | None = None, text: str | None = None,
                 scroll_direction: str | None = None, scroll_amount: int | None = None, duration: float | None = None):
        args = validate(action, executor.display.scaled, coordinate, start_coordinate, text, scroll_direction, scroll_amount, duration)
        answer = executor.perform(args) if action != 'screenshot' else None
        if action == 'cursor_position':
            return answer
        if action not in ('screenshot', 'wait'):
            time.sleep(executor.settle)
        return [Image(data=executor.screenshot(), format='png')]

    return mcp


# --- doctor ---------------------------------------------------------------------------------------------------------------

def doctor(executor=None, png_blank=None):
    """Preflight: [problem, ...] (empty = ready). Checks that the process can post events (Accessibility) and capture the screen (Screen
    Recording: the capture must succeed and must not be blank), with the fix in each message."""
    problems = []
    try:
        ex = executor or Executor()
        info = ex.info()
    except Exception as error:
        return ['vanilla input helper unavailable (needs swiftc): %s' % error]
    if not info.get('post_event'):
        problems.append('Accessibility permission is missing: this process cannot post mouse/keyboard events. Grant it to the terminal that runs the '
                        'harness (System Settings > Privacy & Security > Accessibility), restart the terminal, rerun.')
    if not info.get('screen_capture'):
        problems.append('Screen Recording permission is missing: screenshots would be wallpaper-only or blank. Grant it to the terminal that runs the '
                        'harness (System Settings > Privacy & Security > Screen & System Audio Recording), restart the terminal, rerun.')
    try:
        png = ex.screenshot()
        if (png_blank or looks_blank)(png):
            problems.append('a test screenshot of the main display is blank: grant Screen Recording to the terminal (see above) and make sure the display is awake')
    except Exception as error:
        problems.append('cannot take a screenshot of the main display: %s' % error)
    return problems


def looks_blank(png):
    """A single-colour screen compresses to almost nothing; a real desktop never does. Heuristic on the PNG byte length vs pixel area."""
    m = re.match(rb'\x89PNG\r\n\x1a\n.{4}IHDR(.{4})(.{4})', png, re.S)
    if not m:
        return True
    w, h = int.from_bytes(m.group(1), 'big'), int.from_bytes(m.group(2), 'big')
    return len(png) < max(2000, w * h // 400)


def main_display():
    return Display.from_info(json.loads(subprocess.run([helper_path(), 'info'], capture_output=True, text=True, check=True).stdout))


if __name__ == '__main__':
    build_server(Executor()).run()

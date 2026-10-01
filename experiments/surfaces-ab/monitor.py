"""Interruption monitor: what a run does to the person sitting at the Mac.

`sampler.swift` (compiled once to ~/.cache/computer-use/surfaces-ab/sampler) prints one JSON sample every 200 ms:
frontmost app, cursor position, active displays and on-screen windows. `Detector` (pure, offline-testable) turns the
sample stream into events and counts:

- focus_change: the frontmost application changed. `focus_steals` counts changes to an app other than the one that was
  frontmost when the run began (a return to it is not a steal).
- new_user_window: a window id not seen in the first sample that overlaps a REAL display. A window wholly inside the
  virtual agent display does not count (new_agent_window, informational). A window that straddles the agent display and a
  real one counts. Full-screen click-through overlays owned by the Cua Driver are counted apart (overlay_windows).
- window_to_user_display: a window first seen on the agent display that later overlaps a real display.
- cursor_move: the pointer moved more than CURSOR_EPS px between samples. Counted as samples, bursts (separated by
  BURST_GAP_S of stillness) and total pixels. LIMIT: the sampler cannot tell the user's moves from the agent's, so the
  person must not touch the mouse during a run. The timeline is the evidence; the count is an upper bound.

Limits: a window or focus flicker shorter than the sampling interval can be missed; window titles are empty without Screen
Recording permission (owner and bounds still identify the window). Nothing here posts input or activates a window.
"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get('CUA_CACHE_DIR') or Path.home() / '.cache' / 'computer-use') / 'surfaces-ab'
CURSOR_EPS = 2.0     # px: smaller deltas are sensor noise
BURST_GAP_S = 1.0    # stillness that ends one cursor burst
MIN_WINDOW = 40.0    # px: tooltips and shadows are not windows a person would notice
OVERLAY_OWNERS = ('Cua Driver',)


def rect_of(w):
    return (float(w['x']), float(w['y']), float(w['width']), float(w['height']))


def contains(outer, inner):
    """True when rect `inner` (x, y, w, h) lies wholly inside rect `outer`."""
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def classify_window(window, displays, agent_ids=()):
    """'agent' when the window lies wholly inside one virtual display; 'user' when it overlaps any real display
    (including a window that straddles the agent display and a real one); else 'offscreen'."""
    r = rect_of(window)
    agent = [rect_of(d) for d in displays if d.get('virtual') or d.get('id') in agent_ids]
    real = [rect_of(d) for d in displays if not (d.get('virtual') or d.get('id') in agent_ids)]
    if any(overlaps(r, d) for d in real):
        return 'user'
    if any(contains(d, r) for d in agent):
        return 'agent'
    return 'offscreen'


def display_of(point, displays, agent_ids=()):
    """'agent' | 'user' | 'none' for a cursor position."""
    x, y = point
    for d in displays:
        dx, dy, dw, dh = rect_of(d)
        if dx <= x < dx + dw and dy <= y < dy + dh:
            return 'agent' if (d.get('virtual') or d.get('id') in agent_ids) else 'user'
    return 'none'


def _is_overlay(window):
    return any(str(window.get('owner', '')).startswith(p) for p in OVERLAY_OWNERS)


class Detector:
    def __init__(self, agent_ids=()):
        self.agent_ids = tuple(agent_ids)
        self.t0 = None
        self.front0 = None
        self.front = None
        self.cursor = None
        self.last_move_t = None
        self.seen = {}      # window id -> last class
        self.events = []
        self.counts = {'samples': 0, 'focus_changes': 0, 'focus_steals': 0, 'new_user_windows': 0, 'new_agent_windows': 0,
                       'overlay_windows': 0, 'windows_to_user_display': 0, 'cursor_move_samples': 0, 'cursor_bursts': 0,
                       'cursor_px': 0.0, 'cursor_moves_on_agent_display': 0}

    def _emit(self, t, kind, **fields):
        event = {'t': round(t - self.t0, 3), 'kind': kind, **fields}
        self.events.append(event)
        return event

    def feed(self, sample):
        """Process one sampler line (dict). Returns the events it produced."""
        before = len(self.events)
        t = float(sample['t'])
        displays = sample.get('displays') or []
        self.counts['samples'] += 1
        front = sample.get('front') or {}
        key = front.get('pid')
        cursor = (float(sample['cursor']['x']), float(sample['cursor']['y'])) if sample.get('cursor') else None
        if self.t0 is None:  # the first sample is the baseline: nothing in it counts
            self.t0, self.front0, self.front, self.cursor = t, dict(front), dict(front), cursor
            for w in sample.get('windows') or []:
                self.seen[w['id']] = classify_window(w, displays, self.agent_ids)
            return []
        if key != self.front.get('pid'):
            steal = key != self.front0.get('pid')
            self.counts['focus_changes'] += 1
            self.counts['focus_steals'] += 1 if steal else 0
            self._emit(t, 'focus_change', from_app=self.front.get('name'), to_app=front.get('name'), steal=steal)
            self.front = dict(front)
        for w in sample.get('windows') or []:
            if w['width'] < MIN_WINDOW or w['height'] < MIN_WINDOW:
                continue
            cls = classify_window(w, displays, self.agent_ids)
            prev = self.seen.get(w['id'])
            self.seen[w['id']] = cls
            info = {'id': w['id'], 'app': w.get('owner'), 'title': w.get('title', ''), 'bounds': [w['x'], w['y'], w['width'], w['height']]}
            if prev is None and cls == 'user':
                if _is_overlay(w):
                    self.counts['overlay_windows'] += 1
                    self._emit(t, 'overlay_window', **info)
                else:
                    self.counts['new_user_windows'] += 1
                    self._emit(t, 'new_user_window', **info)
            elif prev is None and cls == 'agent':
                self.counts['new_agent_windows'] += 1
                self._emit(t, 'new_agent_window', **info)
            elif prev == 'agent' and cls == 'user' and not _is_overlay(w):
                self.counts['windows_to_user_display'] += 1
                self._emit(t, 'window_to_user_display', **info)
        if cursor is not None and self.cursor is not None:
            dist = ((cursor[0] - self.cursor[0]) ** 2 + (cursor[1] - self.cursor[1]) ** 2) ** 0.5
            if dist > CURSOR_EPS:
                if self.last_move_t is None or t - self.last_move_t > BURST_GAP_S:
                    self.counts['cursor_bursts'] += 1
                self.last_move_t = t
                self.counts['cursor_move_samples'] += 1
                self.counts['cursor_px'] += dist
                on = display_of(cursor, displays, self.agent_ids)
                self.counts['cursor_moves_on_agent_display'] += 1 if on == 'agent' else 0
                self._emit(t, 'cursor_move', frm=[round(self.cursor[0], 1), round(self.cursor[1], 1)],
                           to=[round(cursor[0], 1), round(cursor[1], 1)], px=round(dist, 1), on=on)
        if cursor is not None:
            self.cursor = cursor
        return self.events[before:]

    def summary(self):
        out = dict(self.counts)
        out['cursor_px'] = round(out['cursor_px'])
        return out


def annoyances(events, summary=None):
    """Free-text, human-readable lines derived from a timeline (no model involved)."""
    notes = []
    for e in events:
        at = '+%.1fs' % e['t']
        if e['kind'] == 'focus_change' and e.get('steal'):
            notes.append('%s: %s took focus from %s' % (at, e.get('to_app') or '?', e.get('from_app') or '?'))
        elif e['kind'] == 'new_user_window':
            notes.append('%s: new window on your screen: %s %s' % (at, e.get('app') or '?', ('"%s"' % e['title']) if e.get('title') else '(untitled)'))
        elif e['kind'] == 'window_to_user_display':
            notes.append('%s: %s window moved onto your screen' % (at, e.get('app') or '?'))
        elif e['kind'] == 'overlay_window':
            notes.append('%s: %s overlay appeared over your screen' % (at, e.get('app') or '?'))
    s = summary or {}
    if s.get('cursor_move_samples'):
        notes.append('cursor moved %d px in %d burst(s) (%d on the agent display); counts agent and user moves alike' % (
            s.get('cursor_px', 0), s.get('cursor_bursts', 0), s.get('cursor_moves_on_agent_display', 0)))
    return notes


def sampler_path():
    """The compiled sampler; built from sampler.swift when missing."""
    binary = CACHE / 'sampler'
    source = HERE / 'sampler.swift'
    if not binary.exists() or binary.stat().st_mtime < source.stat().st_mtime:
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(['swiftc', '-O', str(source), '-o', str(binary)], check=True, capture_output=True)
    return binary


class Monitor:
    """Runs the sampler for the length of one run and writes the timeline (events only) to `timeline_path`."""

    def __init__(self, timeline_path, interval_ms=200, agent_ids=(), command=None):
        self.timeline_path = Path(timeline_path)
        self.interval_ms = interval_ms
        self.detector = Detector(agent_ids)
        self.command = command
        self.proc = None
        self.thread = None
        self.error = None
        self.first = threading.Event()

    def start(self, wait_s=5.0):
        cmd = self.command or [str(sampler_path()), str(self.interval_ms)]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()
        if not self.first.wait(wait_s):
            self.stop()
            raise RuntimeError('monitor produced no sample within %.0fs' % wait_s)

    def _pump(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.detector.feed(json.loads(line))
                except (ValueError, KeyError) as error:
                    self.error = 'bad sample: %s' % error
                    continue
                self.first.set()
        except Exception as error:  # a dying sampler must not kill the run
            self.error = str(error)

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.thread is not None:
            self.thread.join(2)
        self.timeline_path.parent.mkdir(parents=True, exist_ok=True)
        with self.timeline_path.open('w') as fh:
            for event in self.detector.events:
                fh.write(json.dumps(event, sort_keys=True) + '\n')
        summary = self.detector.summary()
        summary['monitor_ok'] = self.error is None and summary['samples'] > 1
        summary['monitor_error'] = self.error
        return summary

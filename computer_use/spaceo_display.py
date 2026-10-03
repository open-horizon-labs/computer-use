"""Opt-in SpaceOKit Stage lifecycle; OH keeps observation, binding and input.

The worker must be explicitly built/configured. Never installs, starts the SpaceO
daemon, resets a journal, or substitutes the user's display. Both backends share
the existing durable OH lifecycle exclusion record.
"""
import os
import math
from pathlib import Path
from spaces_client import SpaceMover, SpaceMoverUnavailable, DEFAULT_BINARY
from display_owners import known_owner_ids, known_display_owners


class SpaceODisplay(SpaceMover):
    def __init__(self, worker=None, placement_binary=None, owner_scan=None, **kwargs):
        configured = worker or os.environ.get('CUA_SPACEO_DISPLAY_WORKER')
        if not configured:
            raise SpaceMoverUnavailable('SpaceO backend requires a prebuilt CUA_SPACEO_DISPLAY_WORKER; nothing was started')
        kwargs.setdefault('serve_timeout', 30)
        kwargs.setdefault('stop_timeout', 15)
        kwargs.setdefault('call_timeout', 5)
        super().__init__(binary=Path(configured), owner_scan=owner_scan, **kwargs)
        self.placement_binary = Path(placement_binary or DEFAULT_BINARY)
        self._baseline = None

    def displays(self):
        value = self.run('--inventory')
        rows = value.get('displays')
        if type(value.get('schemaVersion')) is not int or value['schemaVersion'] != 1 or not isinstance(rows, list) or len(rows) >= 64:
            raise SpaceMoverUnavailable('SpaceO independent online inventory is unreadable')
        if value.get('lifecycleState') != 'ready':
            raise SpaceMoverUnavailable('SpaceO native lifecycle circuit is not ready; no reset or fallback')
        ids = []
        for row in rows:
            if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0:
                raise SpaceMoverUnavailable('SpaceO inventory has invalid identities')
            if any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k]) for k in ('x', 'y', 'width', 'height')) or row['width'] < 0 or row['height'] < 0:
                raise SpaceMoverUnavailable('SpaceO inventory has invalid bounds')
            ids.append(row['id'])
        if len(set(ids)) != len(ids):
            raise SpaceMoverUnavailable('SpaceO inventory has duplicate identities')
        return rows

    def ensure_agent_display(self, width=1920, height=1080):
        self._check_fault()
        if self._serve is None:
            if self.owner_scan():
                raise SpaceMoverUnavailable('other known display owners are present; inspect them before creation, no automatic signals')
            self._baseline = self.displays()
        display = super().ensure_agent_display(width, height)
        try:
            rows = self.displays()
        except Exception:
            self._latch('SpaceO post-attachment inventory/readiness is unknown; retain owner')
        added = {d['id'] for d in rows} - {d['id'] for d in self._baseline}
        existing = [d for d in rows if d['id'] != display]
        if added != {display} or existing != self._baseline:
            self._latch('SpaceO attachment did not preserve independent online topology; retain owner')
        return display

    def _retirement_verified(self):
        rows = self.displays()
        return self._serve is not None and self._serve.returncode == 0 and self._baseline is not None and rows == self._baseline and all(d['id'] != self._display for d in rows)

    def park(self, window_id):
        display = self.ensure_agent_display()
        if not self.placement_binary.exists():
            raise SpaceMoverUnavailable('prebuilt placement helper is unavailable; no fallback')
        helper = SpaceMover(binary=self.placement_binary)
        result = helper.run('move', '--window-id', window_id, '--display', display)
        if not result.get('moved'):
            from spaces_client import WindowNotMoved
            raise WindowNotMoved('window placement was not independently verified', result)
        return result

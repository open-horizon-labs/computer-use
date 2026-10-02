"""Deterministic live PTY fixture; ground truth is a file, not echoed input."""
import json
import os
from pathlib import Path
import sys
import termios
import tty

old = termios.tcgetattr(0)
events = []
selected = 0
choices = ['Alpha', 'Beta']

def draw(message='READY'):
    # Includes alternate screen, cursor addressing, erasure and style-only selection.
    sys.stdout.write('\x1b[2J\x1b[HPTY menu\r\n')
    for i, choice in enumerate(choices):
        sys.stdout.write(('\x1b[7m' if selected == i else '\x1b[0m') + choice + '\x1b[0m\r\n')
    sys.stdout.write(message + '\r\n\x1b[6;1H')
    sys.stdout.flush()

try:
    tty.setraw(0)
    sys.stdout.write('\x1b[?1049h')
    draw()
    while True:
        key = os.read(0, 1)
        if key == b'\x1b':key += os.read(0, 2)
        events.append(key.hex())
        if key in (b'\x1bOB', b'\x1b[B'):
            selected = 1
            draw()
        elif key == b'\r':
            Path(sys.argv[1]).write_text(json.dumps({'selected': choices[selected], 'keys': events, 'argv': sys.argv[2:]}))
            draw('ACCEPTED ' + choices[selected])
        elif key == b'q':break
finally:
    sys.stdout.write('\x1b[?1049l')
    sys.stdout.flush()
    termios.tcsetattr(0, termios.TCSADRAIN, old)

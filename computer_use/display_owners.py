"""Bounded observation of known display-serving helpers; never signals owners."""
import os
import re
import select
import subprocess
import time
from spaces_client import SpaceMoverUnavailable

def known_owner_ids(text):
    owners = []
    for line in text.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0].isdigit() and re.search(r'(?:^|/)(?:space-mover|OHSpaceODisplayWorker)\s+display\s+serve(?:\s|$)', fields[1]):
            owners.append(int(fields[0]))
    return owners


def known_display_owners():
    """Bounded read-only process evidence; never signal any discovered owner."""
    process = subprocess.Popen(['/bin/ps','-axo','pid=,command='], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = bytearray()
    deadline = time.monotonic()+3
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([process.stdout], [], [], max(0, deadline-time.monotonic()))
            if not ready:break
            part = os.read(process.stdout.fileno(),65536)
            if not part:
                process.wait(timeout=max(.01,deadline-time.monotonic()))
                if process.returncode != 0:raise SpaceMoverUnavailable('owner evidence unavailable')
                return known_owner_ids(data.decode('utf-8',errors='strict'))
            data.extend(part)
            if len(data)>1_048_576:break
        raise SpaceMoverUnavailable('owner evidence timed out or exceeded its bound')
    finally:
        # Only this read-only ps child is ours, never any display process it listed.
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        process.stdout.close()

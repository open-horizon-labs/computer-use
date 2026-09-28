"""Bounded JSON-lines transport. A timeout poisons and closes the worker."""
import json
import os
import select
import subprocess
import threading
import time


class JsonWorker:
    def __init__(self, command):
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            raise ValueError('worker command must be a nonempty JSON argv array')
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0, start_new_session=True)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)
        self.buffer = b''
        self.lock = threading.Lock()

    def read(self, deadline):
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError('worker response deadline exceeded')
            block = os.read(self.process.stdout.fileno(), 65536)
            if not block:
                raise RuntimeError('worker closed stdout')
            self.buffer += block
            if len(self.buffer) > 16 * 1024 * 1024:
                raise ValueError('worker response too large')
        line, self.buffer = self.buffer.split(b'\n', 1)
        return json.loads(line)

    def exchange(self, payload, timeout=20):
        deadline = time.monotonic() + timeout
        if not self.lock.acquire(timeout=max(0, timeout)):
            raise TimeoutError('worker busy')
        try:
            data = memoryview((json.dumps(payload) + '\n').encode())
            while data:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([], [self.process.stdin], [], remaining)[1]:
                    raise TimeoutError('worker input deadline exceeded')
                count = os.write(self.process.stdin.fileno(), data)
                data = data[count:]
            return self.read(deadline)
        except Exception:
            self.close()
            raise
        finally:
            self.lock.release()

    def close(self):
        import signal
        if self.process.poll() is None:
            # EOF allows a remote SSH worker to release its GPU allocation.
            self.process.stdin.close()
            try:
                self.process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            if not stream.closed:
                stream.close()

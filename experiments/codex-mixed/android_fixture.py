"""Own one named emulator and park only its process group's fresh window."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'computer_use'))
from agent_display import AgentDisplay
from core import Driver


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--avd', default='OHMixedBenchmark20261002')
    parser.add_argument('--serial', default='emulator-5570')
    parser.add_argument('--emulator', default='/opt/homebrew/share/android-commandlinetools/emulator/emulator')
    parser.add_argument('--folder', type=Path, default=Path('/tmp/cua-mixed-bench'))
    args = parser.parse_args()
    ready = args.folder / 'android-ready.json'
    ready.unlink(missing_ok=True)
    device_list = subprocess.run(['adb','devices'],capture_output=True,text=True,timeout=10,check=True).stdout
    if any(line.split()[0] == args.serial for line in device_list.splitlines()[1:] if line.split()):
        raise RuntimeError('requested serial already exists; refusing to attach or stop it')
    port = args.serial.removeprefix('emulator-')
    if not port.isdigit(): raise RuntimeError('serial must name an emulator console port')
    display = AgentDisplay(mode='required')
    display.launch_rect()
    proc = None
    def stop(signum, frame): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    try:
        with (args.folder / 'android-emulator.log').open('w') as log:
            proc = subprocess.Popen([args.emulator,'-avd',args.avd,'-port',port,'-no-snapshot','-no-audio','-no-boot-anim','-gpu','swiftshader'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        deadline = time.monotonic() + 300
        driver = Driver()
        owned_window = None
        booted = False
        while time.monotonic() < deadline:
            if proc.poll() is not None: raise RuntimeError('owned emulator exited; inspect local emulator log')
            if owned_window is None:
                windows = driver.call('list_windows',{}).get('windows',[])
                matching = []
                for w in windows:
                    if args.avd not in str(w.get('title',w.get('window_title',''))): continue
                    try: owned = os.getpgid(w['pid']) == proc.pid
                    except (KeyError,ProcessLookupError): owned = False
                    if owned: matching.append(w)
                if len(matching) > 1: raise RuntimeError('owned emulator window is ambiguous')
                if matching:
                    owned_window = matching[0]
                    title = owned_window.get('title',owned_window.get('window_title'))
                    display.created(owned_window['window_id'],title,owned_window.get('bounds'))
            try:
                result = subprocess.run(['adb','-s',args.serial,'shell','getprop','sys.boot_completed'],capture_output=True,text=True,timeout=5)
                booted = result.returncode == 0 and result.stdout.strip() == '1'
            except subprocess.TimeoutExpired: booted = False
            if owned_window and booted: break
            time.sleep(1)
        if not owned_window or not booted: raise RuntimeError('owned emulator did not boot and park within bounded setup')
        ready.write_text(json.dumps({'avd':args.avd,'serial':args.serial,'pid':proc.pid,'window':owned_window})+'\n')
        print('owned emulator ready',flush=True)
        while proc.poll() is None: time.sleep(1)
    finally:
        if proc and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try: proc.wait(10)
            except subprocess.TimeoutExpired: os.killpg(proc.pid,signal.SIGKILL);proc.wait()
        display.stop()


if __name__ == '__main__': main()

import subprocess
import sys
import os
import json
import time

runner = os.path.join(os.path.dirname(__file__), 'run_gemma_subprocess.py')
py = sys.executable or 'python'
cmd = [py, '-u', runner]
proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', bufsize=1)

def read_until_ready(timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.1)
            continue
        try:
            obj = json.loads(line.strip())
        except Exception:
            print('RAW:', line.strip())
            continue
        print('EVT:', obj)
        if obj.get('status') == 'ready' or obj.get('event') == 'status' and obj.get('status') == 'ready':
            return True
        if obj.get('event') == 'error':
            print('Runner error:', obj.get('error'))
            return False
    return False

ok = read_until_ready()
if not ok:
    print('Runner not ready')
    proc.kill()
    sys.exit(2)

req = {"id": 1, "cmd": "generate", "prompt": "Say hi from subprocess test", "max_new_tokens": 64}
proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
proc.stdin.flush()

start = time.time()
while time.time() - start < 30:
    line = proc.stdout.readline()
    if not line:
        time.sleep(0.1)
        continue
    try:
        obj = json.loads(line.strip())
    except Exception:
        print('RAW:', line.strip())
        continue
    print('RESP:', obj)
    if obj.get('id') == 1:
        break

proc.stdin.close()
proc.kill()

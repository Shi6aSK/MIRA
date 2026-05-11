import os
import sys
import json
import urllib.request
import urllib.error

def main():
    token = os.environ.get('HUGGINGFACEHUB_API_TOKEN')
    if not token:
        print('HUGGINGFACEHUB_API_TOKEN not set', file=sys.stderr)
        return 2
    model = os.environ.get('HF_MODEL', 'google/gemma-4-E2B-it')
    url = f'https://api-inference.huggingface.co/models/{model}'
    headers = {"Authorization": f"Bearer {token}", 'Content-Type': 'application/json'}
    payload = {"inputs": "hi", "parameters": {"max_new_tokens": 32}, "options": {"wait_for_model": True}}
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    print(f'Calling HF inference for model: {model} ...')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode('utf-8')
            print('HTTP', resp.status)
            try:
                j = json.loads(body)
                print('JSON response:')
                print(json.dumps(j, indent=2, ensure_ascii=False))
            except Exception:
                print('Text response:')
                print(body)
    except urllib.error.HTTPError as e:
        print('HTTP error', e.code)
        try:
            print(e.read().decode('utf-8'))
        except Exception:
            pass
    except Exception as e:
        print('Request error', e)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())

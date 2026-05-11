import time
import os
import sys

from gemma_interface import GemmaInterface, GemmaError

def main():
    model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'gemma'))
    gi = GemmaInterface(model_path=model_dir)
    print('Started GemmaInterface, polling status...')
    timeout = 300
    start = time.time()
    last = None
    while time.time() - start < timeout:
        st = gi.status()
        if st != last:
            print('Status:', st)
            last = st
        if st == 'ready' or st.startswith('inference-api'):
            break
        if st.startswith('error'):
            print('Loader error:', getattr(gi, '_load_err', None))
            return 2
        time.sleep(1)

    st = gi.status()
    print('Final status:', st)
    prompt = 'Write a short joke about saving RAM.'
    try:
        out = gi.generate(prompt, max_new_tokens=64)
        print('Generate output:')
        print(out)
        return 0
    except GemmaError as e:
        print('Generation failed:', e)
        return 3

if __name__ == '__main__':
    sys.exit(main())

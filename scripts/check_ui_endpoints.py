import urllib.request
from urllib.parse import quote

BASE = 'http://127.0.0.1:8000'

def get(path):
    url = BASE + path
    print('\nGET', url)
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            ct = r.getheader('Content-Type')
            data = r.read()
            print('status', r.status)
            print('Content-Type:', ct)
            if ct and 'application/json' in ct:
                print(data.decode('utf-8'))
            else:
                print('bytes', len(data))
    except Exception as e:
        print('ERROR', e)

if __name__ == '__main__':
    get('/api/available-inputs')
    # try preview with unencoded and encoded path
    raw = '/api/preview?path=data/raw/svg/test/南阳名门150.svg'
    enc = '/api/preview?path=' + quote('data/raw/svg/test/南阳名门150.svg', safe='')
    get(raw)
    get(enc)

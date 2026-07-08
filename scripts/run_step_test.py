import urllib.request, json
url='http://127.0.0.1:8000/api/run-step'
data=json.dumps({'step':'dxf2svg','targetDir':'test'}).encode('utf-8')
req=urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'})
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        print(r.status)
        print(r.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print('HTTPError', e.code)
    try:
        print(e.read().decode('utf-8'))
    except Exception:
        pass

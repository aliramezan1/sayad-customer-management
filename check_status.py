import requests, json, websocket
tabs = requests.get('http://127.0.0.1:9223/json').json()
ws = websocket.create_connection(tabs[0]['webSocketDebuggerUrl'])
ws.send(json.dumps({'id': 10, 'method': 'Runtime.evaluate', 'params': {'expression': 'document.title'}}))
print('Title:', json.loads(ws.recv()).get('result',{}).get('result',{}).get('value'))
ws.send(json.dumps({'id': 11, 'method': 'Runtime.evaluate', 'params': {'expression': 'document.querySelectorAll("input").length'}}))
print('Inputs:', json.loads(ws.recv()).get('result',{}).get('result',{}).get('value'))
ws.close()

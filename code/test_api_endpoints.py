import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from api import app

client = TestClient(app)

def test_workspace():
    print('Testing GET /api/workspace...')
    res = client.get('/api/workspace')
    print('Status:', res.status_code)
    ws_data = res.json()
    print('Keys:', list(ws_data.keys()) if isinstance(ws_data, dict) else type(ws_data))

    print('\nTesting POST /api/workspace...')
    res2 = client.post('/api/workspace', json=ws_data)
    print('Status:', res2.status_code)
    print('Response:', res2.json())

def test_assets():
    print('\nTesting POST /api/assets...')
    files = {'file': ('test_file.txt', b'hello world', 'text/plain')}
    res = client.post('/api/assets', files=files)
    print('Status:', res.status_code)
    data = res.json()
    print('Response:', data)
    
    asset_id = data.get('id')
    if asset_id:
        print(f'\nTesting GET /api/assets/{asset_id}...')
        res2 = client.get(f'/api/assets/{asset_id}')
        print('Status:', res2.status_code)
        print('Content:', res2.content)

if __name__ == '__main__':
    test_workspace()
    test_assets()
    print('\nAll API tests completed.')

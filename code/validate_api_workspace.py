from fastapi.testclient import TestClient
import api

client = TestClient(api.app)
response = client.get('/api/workspace')
print(response.status_code)
print(response.text[:200])
if response.status_code != 200:
    raise SystemExit(1)

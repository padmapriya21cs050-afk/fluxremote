import requests

url = "http://127.0.0.1:8001/api/copilot/chat"
payload = {
    "message": "Hello from test",
    "history": [],
    "session_id": "test-session",
    "context": {"connectionStatus": "connected"},
}

resp = requests.post(url, json=payload, timeout=10)
print('status:', resp.status_code)
print('body:', resp.text)

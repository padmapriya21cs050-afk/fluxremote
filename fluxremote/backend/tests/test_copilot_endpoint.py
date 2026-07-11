from fastapi.testclient import TestClient

from fluxremote.backend.main import GeminiAssistant, app


def test_copilot_chat_endpoint_returns_gemini_reply(monkeypatch):
    def fake_chat(message, history=None, context=None):
        assert message == "Explain recursion"
        assert history is not None
        assert history[-1]["content"] == "Explain recursion"
        assert context is not None
        return "Recursion is when a function calls itself."

    monkeypatch.setattr(GeminiAssistant, "chat", staticmethod(fake_chat))

    client = TestClient(app)
    response = client.post(
        "/api/copilot/chat",
        json={
            "message": "Explain recursion",
            "history": [{"role": "user", "content": "Explain recursion"}],
            "session_id": "remote-session-1",
            "context": {"connectionStatus": "connected"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"reply": "Recursion is when a function calls itself.", "fallback": False}

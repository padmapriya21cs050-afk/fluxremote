import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("fluxremote_host_main", MODULE_PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_handle_control_message_ignores_plain_text_heartbeat():
    host = module.FluxHost("ws://example", "device-1", "secret")

    host._handle_control_message("heartbeat")

    assert host.fps == 15


def test_handle_control_message_ignores_non_json_plain_text(monkeypatch):
    host = module.FluxHost("ws://example", "device-1", "secret")
    json_loads_called = False

    def fail_json_loads(payload):
        nonlocal json_loads_called
        json_loads_called = True
        raise AssertionError("json.loads should not be called for plain text control payloads")

    monkeypatch.setattr(module.json, "loads", fail_json_loads)

    host._handle_control_message("plain-text")

    assert json_loads_called is False

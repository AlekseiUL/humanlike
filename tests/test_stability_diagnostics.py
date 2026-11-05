"""Bounded diagnostics never retain exception text or claim provider/model success."""

import os

import pytest

from humanlike_agent.adapters.hermes import HermesAdapter, register
from humanlike_agent.hermes_plugin import build_default_runtime
from humanlike_agent.native import NativeController, Scope, digest


class Host:
    def __init__(self):
        self.hooks = {}
        self.commands = {}

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_command(self, name, fn, **kw):
        self.commands[name] = fn


def test_missing_config_degrades_with_status(tmp_path):
    host = Host()
    register(host, plugin_root=tmp_path)
    assert host.hooks["pre_llm_call"](session_id="s", turn_id="t", user_message="hello") is None
    assert "config_profile_not_loaded" in host.commands["humanlike-status"]("")
    assert str(tmp_path) not in host.commands["humanlike-status"]("")


def test_invalid_config_degrades_with_status(tmp_path):
    root = tmp_path / "examples" / "hermes-humanlike"
    root.mkdir(parents=True)
    (root / "humanlike.toml").write_text('schema = "future-unsupported"')
    host = Host()
    register(host, plugin_root=tmp_path)
    assert host.hooks["pre_llm_call"](session_id="s", turn_id="t", user_message="hello") is None
    assert "config_profile_not_loaded" in host.commands["humanlike-status"]("")


def test_duplicate_turn_and_prepare_are_not_submitted():
    a = HermesAdapter(build_default_runtime())
    assert a.pre_llm_call(user_message="hello") is None
    assert a.status()["reason"] == "invalid_payload"
    payload = dict(session_id="s", turn_id="t", user_message="hello")
    assert a.pre_llm_call(**payload)["context"]
    assert a.status() == {"stage": "prepared", "reason": "returned_to_hook"}
    assert a.pre_llm_call(**payload) is None
    assert a.status()["reason"] == "duplicate_turn"


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only durable memory")
def test_context_tickets_diagnostics_and_current_request_override(tmp_path, monkeypatch):
    c = NativeController(lambda: tmp_path / "memory.sqlite")
    s = Scope(digest("telegram", "fixture"), digest("telegram", "fixture", "chat"), "s", "telegram")
    c._bindings["s"] = s
    c.handle("I agree to local memory", s)
    c.handle("usually keep replies short", s)
    source = dict(platform="telegram", user_id="fixture", chat_id="chat", chat_type="dm")
    text = "Explain this in detail now"
    payload = dict(session_id="s", sender_id="fixture", platform="telegram", user_message=text)
    c.admitted(source=source, platform="telegram", text=text)
    context = c.context(**payload)
    assert "current request/corrections override preferences" in context
    assert '"value": "short"' in context
    assert c._memory(s).recall("reply_length")[0].record.value == "short"
    assert "prepared:not_provider_receipt" in c.handle("status", s)
    assert c.context(**payload) == ""
    assert "missing_ticket" in c.handle("status", s)
    assert "[not_used]" in c.handle("why did you use that", s)
    c.admitted(source=source, platform="telegram", text=text)
    c._tickets["s"] = (digest(text), s, 0)
    assert c.context(**payload) == ""
    assert "stale_or_mismatched_ticket" in c.handle("status", s)
    c.admitted(source=source, platform="telegram", text=text)
    monkeypatch.setattr(c, "_memory", lambda *a: (_ for _ in ()).throw(OSError("private text")))
    assert c.context(**payload).startswith("HUMANLIKE_STATE: error")
    assert c._diagnostics[s.key] == "not_prepared:memory_unavailable"
    assert "private text" not in c.handle("status", s)


def test_unsupported_host_has_explicit_status(monkeypatch):
    import builtins

    from humanlike_agent.hermes_plugin import register as native_register

    original = builtins.__import__

    def absent(name, *a, **kw):
        if name in {"hermes_cli.plugins", "hermes_constants"}:
            raise ImportError("synthetic unsupported host")
        return original(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", absent)
    host = Host()
    native_register(host)
    assert "[unavailable]" in host.commands["humanlike"]("status")
    assert host.hooks["pre_llm_call"](session_id="s", turn_id="t", user_message="hello")

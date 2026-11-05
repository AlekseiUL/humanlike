"""Run with the real Hermes interpreter; no network and a NEW synthetic home only."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--plugin-dir", type=Path)
    args = parser.parse_args()
    args.home.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.environ["HERMES_HOME"] = str(args.home)
    os.environ["HOME"] = str(args.home)
    from gateway.config import Platform
    from gateway.session import SessionSource
    from hermes_cli.plugin_command_dispatch import invoke_plugin_command
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

    if args.plugin_dir:
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "humanlike_export_probe",
            args.plugin_dir / "__init__.py",
            submodule_search_locations=[str(args.plugin_dir)],
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        register = module.register
    else:
        from humanlike_agent.hermes_plugin import register

    manager = PluginManager()
    register(PluginContext(PluginManifest(name="humanlike-agent-kit"), manager))
    handler = manager._plugin_commands["humanlike"]["handler"]
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="fixture-chat",
        user_id="fixture-human",
        chat_type="dm",
        message_id="1",
    )
    counter = 0

    def command(text, src=source, sid="fixture-session"):
        nonlocal counter
        counter += 1
        if isinstance(src, SessionSource):
            src.message_id = str(counter)
        return invoke_plugin_command(
            handler,
            text,
            source=src,
            session_id=sid,
            session_key="fixture-key",
            platform="telegram",
        )

    def approved(text):
        proposal = command(text)
        assert "[confirmation_required]" in proposal, proposal
        match = re.search(r"/humanlike confirm ([a-f0-9]{32})", proposal)
        assert match
        return command("confirm " + match[1])

    def admitted(text):
        return manager.invoke_hook(
            "post_gateway_admission",
            source=source.to_dict(),
            platform="telegram",
            text=text,
            message_id=str(counter),
            session_key="fixture-key",
        )

    def pre(text, **extra):
        nonlocal counter
        counter += 1
        return manager.invoke_hook(
            "pre_llm_call",
            session_id="fixture-session",
            turn_id=f"turn-{counter}",
            user_message=text,
            platform="telegram",
            sender_id="fixture-human",
            conversation_history=[
                {"role": "assistant", "content": "Version 1: Hello.\nVersion 2: Welcome."}
            ],
            **extra,
        )

    initial = command("status")
    assert "[disabled]" in initial, initial
    assert "[enabled]" in approved("I agree to local memory")
    assert "[pending]" in str(admitted("Запомни: обычно отвечай кратко"))
    assert "[empty]" in command("What do you remember?")
    assert "[stored]" in approved("Confirm")
    admitted("the second version")
    enriched = pre("the second version")
    assert "Welcome." in str(enriched) and "general_default" in str(enriched)
    assert "[used]" in command("Why did you use that?")
    assert "HUMANLIKE_REFERENCE_DATA" not in str(pre("continue"))  # no admitted ticket
    admitted("continue")
    assert "HUMANLIKE_REFERENCE_DATA" not in str(pre("continue", parent_session_id="job"))
    assert "[stored]" in approved("Correct that: usually give detailed replies")
    assert "[forgotten]" in approved("Forget that")
    assert "[empty]" in command("What do you remember?")
    assert "[unavailable]" in command("I agree to local memory", source.to_dict())
    foreign = SessionSource(
        platform=Platform.TELEGRAM, chat_id="other-chat", user_id="other-human", chat_type="dm"
    )
    assert "[denied]" in command("What do you remember?", foreign)
    assert "[empty]" in command("What do you remember?", foreign, "other-session")
    assert "[no_save]" in command("Do not save this session")
    assert "[disabled]" in command("Pause memory")
    # Exercise a fresh controller/dispatch registry, not the old handler again.
    manager = PluginManager()
    register(PluginContext(PluginManifest(name="humanlike-agent-kit"), manager))
    handler = manager._plugin_commands["humanlike"]["handler"]
    assert "[disabled]" in command("status")
    assert "no_save=True" in command("status")
    assert "[empty]" in command("What do you remember?")
    assert "[enabled]" in approved("I agree to local memory")
    assert "[no_save]" in str(admitted("Usually keep replies short"))
    assert "[empty]" in command("What do you remember?")
    print(
        json.dumps(
            {
                "status": "PASS",
                "native_interfaces": [
                    "PluginContext",
                    "PluginManager",
                    "invoke_plugin_command",
                    "SessionSource",
                ],
                "journey": "consent-propose-confirm-recall-correct-forget",
                "private_data": "not_read",
                "network": "not_used",
            }
        )
    )


if __name__ == "__main__":
    main()

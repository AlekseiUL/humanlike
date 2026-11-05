"""Pip entry-point adapter for Hermes Agent plugin discovery."""

from __future__ import annotations

from .adapters.hermes import HermesAdapter
from .persona import Persona, PersonaSpine
from .runtime import HumanlikeRuntime, RuntimeConfig

_PROFILE_ID = "hermes-humanlike"
_IDENTITY = "Hermes is a portable conversational AI designed for clear, thoughtful collaboration."
_VOICE = "Natural and warm, with direct language, light wit, and respect for the user's pace."
_VALUES = "Truth before performance; consent before persistence; useful clarity before ceremony."
_BOUNDARIES = (
    "State AI nature plainly when asked. Protect privacy, admit uncertainty, and never encourage "
    "dependency or exclusivity."
)


def build_default_runtime() -> HumanlikeRuntime:
    """Build the memory-off starter runtime embedded in the installed wheel."""

    persona = Persona(
        spine=PersonaSpine(
            identity=_IDENTITY,
            voice=_VOICE,
            values=_VALUES,
        ),
        declared_boundaries=_BOUNDARIES,
    )
    return HumanlikeRuntime(
        RuntimeConfig(
            profile_id=_PROFILE_ID,
            normal_context_chars=1_200,
            deep_context_chars=2_400,
        ),
        persona,
    )


def register(context: object) -> None:
    """Register behavior hooks plus the supported native human-control bridge."""
    from .native import NativeController

    adapter = HermesAdapter(build_default_runtime())
    register_command = getattr(context, "register_command", None)
    try:
        from hermes_cli.plugins import VALID_HOOKS
        from hermes_constants import get_hermes_home

        supported = "post_gateway_admission" in VALID_HOOKS and callable(register_command)
        root = get_hermes_home()
    except ImportError:
        supported = False
    if not supported:
        adapter.register(context)
        if callable(register_command):
            register_command(
                "humanlike",
                lambda raw_args, **kw: (
                    "[unavailable] Native memory requires Hermes post_gateway_admission "
                    "and transport-aware slash dispatch. "
                    "Ordinary memory-off behavior remains available."
                ),
                description="Humanlike compatibility status",
            )
        return
    controller = NativeController(lambda: root / "plugin-data" / "humanlike" / "memory.sqlite")

    def pre(**payload):
        base = adapter.pre_llm_call(**payload)
        extra = controller.context(**payload)
        if not base:
            return None
        return {"context": base["context"] + ("\n\n" + extra if extra else "")}

    def finalize(**payload):
        controller.finalize(**payload)
        adapter.on_session_finalize(**payload)

    context.register_hook("pre_llm_call", pre)
    context.register_hook("transform_llm_output", adapter.transform_llm_output)
    context.register_hook("post_llm_call", adapter.post_llm_call)
    context.register_hook("on_session_finalize", finalize)
    context.register_hook("post_gateway_admission", controller.admitted)
    register_command(
        "humanlike",
        controller.command,
        description="Local memory consent, controls and RU/EN help",
        args_hint="<request>",
    )


__all__ = ["build_default_runtime", "register"]

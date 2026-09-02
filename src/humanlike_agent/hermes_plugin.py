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
    """Register the wheel-installed plugin with a Hermes PluginContext."""

    HermesAdapter(build_default_runtime()).register(context)


__all__ = ["build_default_runtime", "register"]

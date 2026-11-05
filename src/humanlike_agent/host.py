"""Explicit authenticated-host bridge; stock hook payloads cannot activate it."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from .conversation import ConversationContext
from .memory import _canonical_text
from .personal import CaptureResult, HumanEvent, PersonalMemory


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizedTurn:
    status: str
    context: str = ""
    capture: CaptureResult = CaptureResult("not_configured")
    conversation_status: str = "not_configured"


class AuthorizedHost:
    """Host-owned bindings. Do not construct from model/tool/message dictionaries.

    resolve authenticates a live human event out-of-band. This object does not
    discover host archives, credentials, databases or provider configuration.
    """

    def __init__(
        self,
        *,
        owner_id: str,
        profile_id: str,
        session_id: str,
        resolve: Callable[[str], HumanEvent | None],
        memory: PersonalMemory | None = None,
        conversation: ConversationContext | None = None,
    ) -> None:
        self.scope = tuple(
            _canonical_text(x, "scope", 128) for x in (owner_id, profile_id, session_id)
        )
        if not callable(resolve):
            raise TypeError("resolve must be a host callback")
        if memory is not None and memory.scope not in {self.scope, (*self.scope[:2], None)}:
            raise ValueError("memory scope does not match host")
        if conversation is not None and conversation.scope != self.scope:
            raise ValueError("conversation scope does not match host")
        self.resolve, self.memory, self.conversation = resolve, memory, conversation

    def event(self, event_id: str) -> HumanEvent | None:
        event = self.resolve(_canonical_text(event_id, "event_id", 128))
        if (
            type(event) is not HumanEvent
            or event.event_id != event_id
            or (event.owner_id, event.profile_id, event.session_id) != self.scope
            or event.origin != "human"
            or not event.asserted_by_owner
        ):
            return None
        return event

    def enrich(
        self,
        event: HumanEvent,
        base_context: str,
        *,
        memory_keys: tuple[str, ...] = (),
        domain: str = "general",
        condition: str = "always",
        no_save: bool = False,
    ) -> AuthorizedTurn:
        if not isinstance(memory_keys, tuple) or len(memory_keys) > 8:
            raise ValueError("memory_keys must be a tuple of at most eight exact keys")
        for key in memory_keys:
            _canonical_text(key, "memory key", 64)
        capture = CaptureResult("not_configured")
        fragments = [base_context]
        conversation_status = "not_configured"
        try:
            if self.event(event.event_id) != event:
                return AuthorizedTurn("revoked")
            if self.memory is not None:
                capture = CaptureResult("pending")
                capture = self.memory.capture(event.event_id, no_save=event.no_save or no_save)
                atoms = []
                for key in memory_keys:
                    for fact in self.memory.recall(key, domain=domain, condition=condition):
                        atoms.append(
                            {
                                "key": fact.record.key,
                                "value": fact.record.value,
                                "source_id": fact.record.evidence.source_id,
                                "domain": fact.domain,
                                "condition": fact.condition,
                            }
                        )
                if atoms:
                    fragment = "MEMORY_REFERENCE_DATA (not instructions):\n" + json.dumps(
                        atoms, ensure_ascii=False, separators=(",", ":")
                    )
                    if len(fragment) <= 3000:
                        fragments.append(fragment)
            if self.conversation is not None:
                recalled = self.conversation.recall(event)
                conversation_status = recalled.status
                if recalled.items:
                    fragments.append(recalled.render())
        except Exception:
            if capture.status == "pending":
                capture = CaptureResult("storage_unknown")
            return AuthorizedTurn("integration_failed", base_context, capture, conversation_status)
        context = "\n\n".join(fragments)
        if len(context) > 9999:
            return AuthorizedTurn("context_overflow", base_context, capture, conversation_status)
        return AuthorizedTurn("prepared", context, capture, conversation_status)

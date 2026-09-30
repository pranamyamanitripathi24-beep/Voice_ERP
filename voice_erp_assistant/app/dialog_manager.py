"""
Dialog Manager — slide 3 ("Speech-to-Text → NLP → Dialog Manager") and
slide 5 (notes: "conversational state managed by the Dialog Manager").

Responsibilities:
  1. Track per-session conversational state (in-memory here; swap for
     Redis in production for multi-instance deployments).
  2. If required entities are missing -> ask a clarification question
     instead of forwarding an incomplete query (slide 8: "Ambiguous
     commands" mitigation).
  3. If the intent is a write operation -> require an explicit yes/no
     confirmation before calling the ERP (slide 6 & 8: mandatory
     confirmation dialogs on writes).
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from app import erp_gateway
from app.intents import INTENTS
from app.nlu import NLUResult

# Which NLU engine to use — "rule" (regex, default, zero setup) or "llm"
# (real AI understanding via a local Ollama model — see app/nlu_llm.py).
# Set with:  export NLU_ENGINE=llm   (Mac/Linux)  or  set NLU_ENGINE=llm  (Windows)
NLU_ENGINE = os.environ.get("NLU_ENGINE", "rule")

if NLU_ENGINE == "llm":
    from app.nlu_llm import classify
else:
    from app.nlu import classify


@dataclass
class Session:
    session_id: str
    employee_id: Optional[str] = None          # simulated "logged in" user
    role: str = "admin"
    pending_intent: Optional[str] = None        # intent awaiting confirmation
    pending_entities: dict = field(default_factory=dict)
    awaiting_clarification_for: Optional[str] = None  # entity name we asked about
    pending_uncertain: dict = field(default_factory=dict)  # entity_name -> "Name (ID)"
    confirming_entity: Optional[str] = None     # entity name currently being double-checked


# In-memory session store. Replace with Redis/DB for a real multi-user deployment.
_SESSIONS: dict[str, Session] = {}


def get_session(session_id: str, employee_id: Optional[str] = None, role: str = "admin") -> Session:
    if session_id not in _SESSIONS:
        _SESSIONS[session_id] = Session(session_id=session_id, employee_id=employee_id, role=role)
    elif employee_id:
        _SESSIONS[session_id].employee_id = employee_id
        _SESSIONS[session_id].role = role
    return _SESSIONS[session_id]


CLARIFY_PROMPTS = {
    "item_id": "Which item? Please give me the item ID, like P-102.",
    "period": "Which period — today, this month, or last month?",
    "employee_id": "I don't have your employee ID on file for this session. What's your employee ID?",
    "delta": "How many units?",
    "quantity": "How many units should I request?",
}


def handle_utterance(
    session_id: str,
    text: str,
    employee_id: Optional[str] = None,
    role: str = "admin",
) -> dict:
    """
    Main Dialog Manager entry point. Returns a dict:
      {
        "reply": str,                # natural-language response (feed to TTS)
        "awaiting_confirmation": bool,
        "awaiting_clarification": bool,
        "result": dict | None,       # raw ERP result, if a query executed
      }
    """
    session = get_session(session_id, employee_id, role)
    normalized = text.strip().lower()

    # --- Case 00: friendly small talk / greeting flow ---
    if re.match(r"^(hi|hello|hey|good morning|good evening|good afternoon|yo)\b", normalized):
        return {
            "reply": "Hello! I’m your ERP assistant. I can help with stock, attendance, and sales. What would you like to check?",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"how are you", "how are you doing", "how's it going", "how is it going"}:
        return {
            "reply": "I’m doing well and ready to help with your ERP tasks. Ask me about stock, attendance, or sales.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"what can you do", "what are you able to do", "help me"}:
        return {
            "reply": "I can check inventory, summarize attendance, review sales, and help with standard ERP operations. Just ask me in plain language.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"who are you", "who are you?", "what is your name", "what are you"}:
        return {
            "reply": "I’m your ERP assistant. I help with inventory, attendance, and sales questions in plain language.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"can you help me with inventory", "help me with inventory", "inventory help"}:
        return {
            "reply": "Absolutely. You can ask me things like 'check stock for P-102' or 'show inventory levels for valve parts'.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"what is my attendance", "show my attendance", "attendance summary", "my attendance"}:
        return {
            "reply": "I can summarize your attendance. Try asking: 'show my attendance' or 'how many days have I attended this month?'.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"can you summarize sales", "summarize sales", "sales summary"}:
        return {
            "reply": "Yes. Ask me for today’s sales, this month, or last month and I’ll summarize the report for you.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"good job", "nice work", "great job", "well done"}:
        return {
            "reply": "Thank you! I’m here to help you stay on top of ERP operations.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"thank you", "thanks", "thank u"}:
        return {
            "reply": "You’re welcome. I’m happy to help.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    if normalized in {"bye", "goodbye", "see you later"}:
        return {
            "reply": "Goodbye! I’ll be here when you need me.",
            "awaiting_confirmation": False,
            "awaiting_clarification": False,
            "result": None,
        }

    # --- Case 0: we asked "did you mean X?" for a low-confidence match ---
    # (this is the safety net against misheard voice input — see
    # app/entity_resolver.py; it catches STT mistakes before they reach the ERP)
    if session.confirming_entity:
        decision = text.strip().lower()
        entity_name = session.confirming_entity
        if decision in ("yes", "y", "correct", "right", "yeah", "yep"):
            session.confirming_entity = None
            return _advance_uncertain_or_continue(session)
        elif decision in ("no", "n", "wrong", "nope"):
            session.pending_entities.pop(entity_name, None)
            session.confirming_entity = None
            session.pending_uncertain = {}
            session.awaiting_clarification_for = entity_name
            return {"reply": CLARIFY_PROMPTS.get(entity_name, f"Can you clarify {entity_name}?"),
                    "awaiting_confirmation": False, "awaiting_clarification": True,
                    "result": None}
        else:
            return {"reply": "Please say yes or no.",
                    "awaiting_confirmation": True, "awaiting_clarification": False,
                    "result": None}

    # --- Case 1: we previously asked a clarifying question ---
    if session.awaiting_clarification_for:
        entity_name = session.awaiting_clarification_for
        # Re-run NLU on the follow-up utterance to pull out just that entity
        follow_up = classify(text)
        value = follow_up.entities.get(entity_name)
        # also allow bare values like "P-102" or "last month" typed directly
        if value is None and entity_name in ("item_id", "employee_id"):
            value = text.strip().upper()
        elif value is None and entity_name == "period":
            value = text.strip().lower().replace(" ", "_")
        elif value is None and entity_name == "quantity":
            quantity_match = re.fullmatch(r"\s*(\d+)(?:\s*(?:units?|pieces?))?\s*", text, re.IGNORECASE)
            value = int(quantity_match.group(1)) if quantity_match else None

        session.pending_entities[entity_name] = value
        session.awaiting_clarification_for = None
        return _continue_pending(session)

    # --- Case 2: we previously asked for write confirmation ---
    if session.pending_intent:
        decision = text.strip().lower()
        if decision in ("yes", "y", "confirm", "yes please", "do it"):
            return _execute(session, session.pending_intent, session.pending_entities)
        elif decision in ("no", "n", "cancel", "stop"):
            intent, session.pending_intent = session.pending_intent, None
            session.pending_entities = {}
            return {"reply": "Okay, cancelled. Nothing was changed.",
                    "awaiting_confirmation": False, "awaiting_clarification": False,
                    "result": None}
        else:
            return {"reply": "Please say yes to confirm or no to cancel.",
                    "awaiting_confirmation": True, "awaiting_clarification": False,
                    "result": None}

    # --- Case 3: fresh utterance ---
    nlu_result = classify(text)
    if nlu_result.intent == "unknown":
        return {"reply": "Sorry, I didn't understand that. You can ask things like "
                          "'check stock for P-102' or 'mark my attendance'.",
                "awaiting_confirmation": False, "awaiting_clarification": False,
                "result": None}

    entities = dict(nlu_result.entities)
    uncertain = entities.pop("_uncertain", {})
    # auto-fill employee_id from session (simulates "resolves employee identity
    # from session context" on slide 9)
    if "employee_id" in INTENTS[nlu_result.intent]["required_entities"] and not entities.get("employee_id"):
        if session.employee_id:
            entities["employee_id"] = session.employee_id

    session.pending_intent = nlu_result.intent
    session.pending_entities = entities
    session.pending_uncertain = uncertain
    return _advance_uncertain_or_continue(session)


def _advance_uncertain_or_continue(session: Session) -> dict:
    """If any extracted entity was a low-confidence fuzzy match (likely a
    misheard word), ask the user to confirm it before doing anything else —
    this is what stops a mis-transcribed name from silently updating the
    wrong record. Once all uncertain entities are confirmed, proceeds
    exactly like a normal (confident) request."""
    if session.pending_uncertain:
        entity_name, label = next(iter(session.pending_uncertain.items()))
        del session.pending_uncertain[entity_name]
        session.confirming_entity = entity_name
        return {"reply": f"I think I heard {label} — is that right? (yes/no)",
                "awaiting_confirmation": True, "awaiting_clarification": False,
                "result": None}
    return _continue_pending(session)


def _continue_pending(session: Session) -> dict:
    intent = session.pending_intent
    spec = INTENTS[intent]
    missing = [e for e in spec["required_entities"] if not session.pending_entities.get(e)]

    if missing:
        entity_name = missing[0]
        session.awaiting_clarification_for = entity_name
        return {"reply": CLARIFY_PROMPTS.get(entity_name, f"Can you clarify {entity_name}?"),
                "awaiting_confirmation": False, "awaiting_clarification": True,
                "result": None}

    if spec["is_write"]:
        return {"reply": _confirmation_prompt(intent, session.pending_entities),
                "awaiting_confirmation": True, "awaiting_clarification": False,
                "result": None}

    # Read operation, all entities present -> execute immediately
    return _execute(session, intent, session.pending_entities)


def _confirmation_prompt(intent: str, entities: dict) -> str:
    if intent == "mark_attendance":
        return f"Mark attendance as present for employee {entities.get('employee_id')}. Confirm? (yes/no)"
    if intent == "update_stock":
        verb = "add" if entities.get("delta", 0) >= 0 else "remove"
        return (f"{verb.capitalize()} {abs(entities.get('delta', 0))} units "
                f"{'to' if verb == 'add' else 'from'} {entities.get('item_id')}. Confirm? (yes/no)")
    if intent == "create_purchase_request":
        return (f"Create a purchase request for {entities.get('quantity')} units of "
                f"{entities.get('item_id')} from its assigned supplier? Confirm? (yes/no)")
    return f"Confirm {intent} with {entities}? (yes/no)"


def _execute(session: Session, intent: str, entities: dict) -> dict:
    session.pending_intent = None
    session.pending_entities = {}
    result = erp_gateway.dispatch(
        intent, entities, role=session.role, actor_employee_id=session.employee_id
    )
    reply = erp_gateway.format_reply(intent, entities, result)
    return {"reply": reply, "awaiting_confirmation": False,
            "awaiting_clarification": False, "result": result}

"""
LLM-based NLU — this is the actual "AI" version of the Processing Layer,
as opposed to app/nlu.py's regex pattern matching.

The difference that matters:
  - app/nlu.py:      if the sentence doesn't match a written pattern, it fails.
  - app/nlu_llm.py:  the model reads the sentence and figures out the intent
                      even if it has never seen that exact phrasing before.

It works by sending the user's raw sentence to a small language model
running locally on your laptop (via Ollama — free, no API key, no
internet needed after the one-time model download) with instructions to
return structured JSON. The model does the "understanding"; this file
just parses its answer into the same NLUResult shape app/nlu.py uses, so
nothing else in the project (dialog_manager.py, erp_gateway.py) has to
change to use it.

One-time setup on your laptop (not in this sandbox):
  1. Install Ollama:            https://ollama.com  (free, Win/Mac/Linux)
  2. Pull a small free model:   ollama pull llama3.2:1b
     (about 1.3GB, runs fine on a normal laptop CPU, no GPU required)
  3. That's it — Ollama runs a local server automatically at
     http://localhost:11434 whenever it's installed and running.

Switch the project to use this engine by setting an environment variable:
  Windows:    set NLU_ENGINE=llm
  Mac/Linux:  export NLU_ENGINE=llm
before running `python demo.py` or `uvicorn app.main:app --reload`.
"""

import json
import requests

from app.nlu import NLUResult, classify as rule_based_classify
from app.intents import INTENTS

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:1b"  # swap for qwen2.5:1.5b or any other pulled model

SYSTEM_PROMPT = """You are the NLU engine for a voice-controlled ERP assistant.
Given a user's spoken request, output ONLY a JSON object (no other text, no markdown) with:
  "intent": exactly one of {intents}
  "entities": a dict with any of these keys you can confidently extract:
    - item_id (e.g. "P-102") -- only if a clear code was spoken
    - item_name (free text, e.g. "hydraulic valve") -- if the item was named instead of coded
    - employee_id (e.g. "E-001") -- only if a clear code was spoken
    - employee_name (free text, e.g. "Asha Rao") -- if the employee was named instead of coded
    - period: one of "today", "this_month", "last_month"
    - delta: integer, positive to add stock, negative to remove stock
    - quantity: positive integer requested on a purchase request

Examples of the kind of phrasing variation you must handle:
"How much attendance do I have" -> {{"intent": "get_attendance_summary", "entities": {{}}}}
"Am I eligible for exams based on attendance" -> {{"intent": "check_exam_eligibility", "entities": {{}}}}
"Show my attendance for this semester" -> {{"intent": "get_attendance_summary", "entities": {{}}}}
"What's the stock on P-205" -> {{"intent": "check_stock", "entities": {{"item_id": "P-205"}}}}
"Check stock on the hydraulic valve" -> {{"intent": "check_stock", "entities": {{"item_name": "hydraulic valve"}}}}
"Which items are low in stock?" -> {{"intent": "get_low_stock_items", "entities": {{}}}}
"Create a purchase request for 24 units of P-102" -> {{"intent": "create_purchase_request", "entities": {{"item_id": "P-102", "quantity": 24}}}}
"Mark attendance for Asha Rao" -> {{"intent": "mark_attendance", "entities": {{"employee_name": "Asha Rao"}}}}
"Give me last month's revenue" -> {{"intent": "get_sales_report", "entities": {{"period": "last_month"}}}}
"How much did we spend this month?" -> {{"intent": "get_expense_summary", "entities": {{"period": "this_month"}}}}
"Show me the highest expenses" -> {{"intent": "get_top_expenses", "entities": {{}}}}
"Generate this month's sales report" -> {{"intent": "get_sales_report", "entities": {{"period": "this_month"}}}}
"Take 10 units off P-301" -> {{"intent": "update_stock", "entities": {{"item_id": "P-301", "delta": -10}}}}

If nothing matches any known intent, use "intent": "unknown".
Respond with JSON only, nothing else — no explanation, no markdown fences."""


def _resolve_names(entities: dict) -> tuple[dict, dict]:
    """Turns any item_name/employee_name the LLM extracted into a real
    item_id/employee_id via the same fuzzy matcher the rule-based engine
    uses, so both NLU engines share the same misheard-input safety net."""
    from app import entity_resolver

    uncertain = {}
    if "item_name" in entities and "item_id" not in entities:
        value, confirm_label = entity_resolver.resolve_with_confidence("item", entities.pop("item_name"))
        if value:
            entities["item_id"] = value
            if confirm_label:
                uncertain["item_id"] = confirm_label
    if "employee_name" in entities and "employee_id" not in entities:
        value, confirm_label = entity_resolver.resolve_with_confidence("employee", entities.pop("employee_name"))
        if value:
            entities["employee_id"] = value
            if confirm_label:
                uncertain["employee_id"] = confirm_label
    return entities, uncertain



def classify(text: str) -> NLUResult:
    """Drop-in replacement for app.nlu.classify() — same return type,
    but understands meaning instead of matching fixed patterns."""
    prompt = SYSTEM_PROMPT.format(intents=list(INTENTS.keys()))
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": f'{prompt}\n\nUser request: "{text}"\nJSON:',
                "stream": False,
                "format": "json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()["response"]
        parsed = json.loads(raw)

        intent = parsed.get("intent", "unknown")
        entities = parsed.get("entities") or {}
        if intent not in INTENTS:
            intent = "unknown"

        # Resolve any free-text item/employee name to a real ID, and flag
        # low-confidence matches so the Dialog Manager double-checks them —
        # same safety net the rule-based engine uses (see entity_resolver.py).
        entities, uncertain = _resolve_names(entities)
        if uncertain:
            entities["_uncertain"] = uncertain

        return NLUResult(intent=intent, entities=entities, confidence=0.85)

    except Exception as e:
        # Ollama not installed/running, or the model returned bad JSON.
        # Fail safe rather than crash: fall back to the rule-based engine
        # so the app still responds to the commands it does recognize.
        print(f"[nlu_llm] LLM unavailable, falling back to rule-based NLU ({e})")
        return rule_based_classify(text)

"""
AI Processing Layer — NLU (Intent + Entity Extraction), slide 3/4.

This is a deliberately dependency-free, rule-based NLU engine so the whole
pipeline works out of the box with no API key and no model download.
It's a stand-in for the "Rasa (on-prem)" or "LangChain + GPT" options
mentioned on slide 4/7 — swap `classify()` for a call to either without
touching any other file, since everything downstream only depends on the
NLUResult shape.

To upgrade to an LLM-based NLU later: replace the body of `classify()`
with a call to your LLM, prompting it to return JSON:
    {"intent": "...", "entities": {...}}
and keep the same return type.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from app import entity_resolver


@dataclass
class NLUResult:
    intent: str
    entities: dict = field(default_factory=dict)
    confidence: float = 1.0


# Order matters: more specific patterns first.
_INTENT_PATTERNS = [
    ("create_purchase_request", [
        r"\b(create|raise|make|submit)\b.*\bpurchase (request|order)\b",
    ]),
    ("get_low_stock_items", [
        r"\b(low stock|low in stock|below reorder)\b",
        r"\bwhich items\b.*\blow\b.*\bstock\b",
        r"\bitems\b.*\bneed to? reorder\b",
    ]),
    ("get_top_expenses", [
        r"\b(highest|largest|top)\b.*\bexpenses?\b",
    ]),
    ("get_expense_summary", [
        r"\b(spend|spent|expenditure|expenses?)\b.*\b(this month|last month|today)\b",
    ]),
    ("check_stock", [
        r"\b(check|show|get|what'?s|how many)\b.*\bstock\b",
        r"\bstock\b.*\bfor\b",
        r"\binventory\b.*\b(level|count)\b",
    ]),
    ("update_stock", [
        r"\b(add|remove|restock|consume|use)\b.*\b(units?|stock|item)\b",
    ]),
    ("mark_attendance", [
        r"\bmark\b.*\battendance\b",
        r"\bclock (in|out)\b",
        r"\bi'?m (present|here)\b",
    ]),
    ("get_sales_report", [
        r"\b(sales|revenue)\b.*\breport\b",
        r"\btotal sales\b",
        r"\bget\b.*\bsales\b",
    ]),
    ("check_exam_eligibility", [
        r"\beligible\b.*\bexam",
        r"\bexam\b.*\beligib",
    ]),
    ("get_attendance_summary", [
        r"\bhow much attendance\b",
        r"\bmy attendance\b.*\b(percent|percentage|record|summary|this)\b",
        r"\battendance\b.*\b(percent|percentage)\b",
    ]),
]

_ITEM_ID_RE = re.compile(r"\b([A-Za-z]{1,3}-\d{2,5})\b")
_EMPLOYEE_ID_RE = re.compile(r"\b(E-\d{2,5})\b", re.IGNORECASE)
_DELTA_RE = re.compile(r"\b(\d+)\s*(units?|pieces?)?\b")

_PERIOD_MAP = {
    "last month": "last_month",
    "this month": "this_month",
    "today": "today",
}


def _extract_entities(text: str, intent: str) -> dict:
    entities = {}
    uncertain = {}
    text_lower = text.lower()

    item_match = _ITEM_ID_RE.search(text)
    if item_match:
        entities["item_id"] = item_match.group(1).upper()
    elif intent in ("check_stock", "update_stock", "create_purchase_request"):
        # No clean code found (likely mangled by STT) — try matching the
        # item's actual name instead, which speech engines handle far better.
        value, confirm_label = entity_resolver.resolve_with_confidence("item", text)
        if value:
            entities["item_id"] = value
            if confirm_label:
                uncertain["item_id"] = confirm_label

    emp_match = _EMPLOYEE_ID_RE.search(text)
    if emp_match:
        entities["employee_id"] = emp_match.group(1).upper()
    elif intent in ("mark_attendance", "get_attendance_summary", "check_exam_eligibility"):
        value, confirm_label = entity_resolver.resolve_with_confidence("employee", text)
        if value:
            entities["employee_id"] = value
            if confirm_label:
                uncertain["employee_id"] = confirm_label

    for phrase, period in _PERIOD_MAP.items():
        if phrase in text_lower:
            entities["period"] = period
            break

    if intent == "update_stock":
        # crude sign detection: "remove"/"consume"/"use" -> negative delta
        num_match = _DELTA_RE.search(text_lower)
        if num_match:
            qty = int(num_match.group(1))
            if any(w in text_lower for w in ["remove", "consume", "use", "used"]):
                qty = -qty
            entities["delta"] = qty

    if intent == "create_purchase_request":
        quantity_match = re.search(r"\b(\d+)\s*(?:units?|pieces?)\b", text_lower)
        if quantity_match:
            entities["quantity"] = int(quantity_match.group(1))

    if uncertain:
        entities["_uncertain"] = uncertain
    return entities


def classify(text: str) -> NLUResult:
    """Rule-based intent classifier + entity extractor.

    Returns NLUResult(intent='unknown', ...) if nothing matches, which the
    Dialog Manager turns into a clarification prompt rather than a crash.
    """
    text_clean = text.strip()
    text_lower = text_clean.lower()

    for intent, patterns in _INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text_lower):
                entities = _extract_entities(text_clean, intent)
                return NLUResult(intent=intent, entities=entities, confidence=0.9)

    # Fallback: no pattern matched
    return NLUResult(intent="unknown", entities={}, confidence=0.0)

"""
Fixes a common cause of "my voice isn't recognized accurately":
alphanumeric codes ("P-102") are difficult for speech recognition to
transcribe because "P one oh two" carries little acoustic signal to
distinguish P-102 from P-100 or P-192.

Item and employee *names* ("Hydraulic Valve", "Vikram Nair") are real
words the STT model has actually seen in training and is much better at.
This module lets the user say either, and resolves a possibly-misheard
name to the closest real database record using fuzzy string matching
(difflib, in Python's standard library — no extra install needed),
returning a confidence score so the Dialog Manager can decide whether to
just proceed or double-check with the user first.
"""

import difflib

from app import database


def _best_match(text_lower: str, id_map: dict, name_map: dict, cutoff: float):
    # 1. Exact code match (fast path — regex already found "P-102" in nlu.py
    #    and is just confirming it exists)
    for id_lower, real_id in id_map.items():
        if id_lower in text_lower:
            return real_id, real_id, 1.0

    # 2. Fuzzy match by finding the name's WORDS inside the sentence, not by
    #    comparing the whole sentence to the name. This matters because real
    #    voice commands embed the name in a longer sentence ("mark
    #    attendance for asha rao"), and comparing that entire string to
    #    "asha rao" scores low even though the name is right there.
    text_tokens = text_lower.split()
    best_id, best_label, best_score = None, None, 0.0
    for name_lower, real_id in name_map.items():
        name_tokens = name_lower.split()
        if not name_tokens:
            continue
        per_word_scores = [
            max((difflib.SequenceMatcher(None, nt, tt).ratio() for tt in text_tokens), default=0.0)
            for nt in name_tokens
        ]
        score = sum(per_word_scores) / len(per_word_scores)
        if score > best_score:
            best_id, best_label, best_score = real_id, name_lower, score

    if best_score >= cutoff:
        return best_id, best_label, best_score
    return None, None, 0.0


def resolve_item(text_fragment: str, cutoff: float = 0.5):
    """Returns (item_id, matched_label, score) or (None, None, 0.0)."""
    with database.get_conn() as conn:
        rows = conn.execute("SELECT item_id, name FROM inventory").fetchall()
    id_map = {r["item_id"].lower(): r["item_id"] for r in rows}
    name_map = {r["name"].lower(): r["item_id"] for r in rows}
    return _best_match(text_fragment.lower(), id_map, name_map, cutoff)


def resolve_employee(text_fragment: str, cutoff: float = 0.5):
    """Returns (employee_id, matched_label, score) or (None, None, 0.0)."""
    with database.get_conn() as conn:
        rows = conn.execute("SELECT employee_id, name FROM employees").fetchall()
    id_map = {r["employee_id"].lower(): r["employee_id"] for r in rows}
    name_map = {r["name"].lower(): r["employee_id"] for r in rows}
    return _best_match(text_fragment.lower(), id_map, name_map, cutoff)


def resolve_with_confidence(kind: str, text_fragment: str, confident_threshold: float = 0.85):
    """High-level helper used by the NLU layer.

    Returns (value, confirmation_label):
      - (None, None)             — nothing close enough found; caller should
                                    treat this entity as still missing.
      - (value, None)            — confident match; use it directly.
      - (value, "Name (ID)")     — uncertain match; caller should ask the
                                    user "did you mean X?" before acting on it.
    """
    resolver = resolve_item if kind == "item" else resolve_employee
    value, label, score = resolver(text_fragment)
    if value is None:
        return None, None
    if score >= confident_threshold:
        return value, None
    return value, f"{label.title()} ({value})"

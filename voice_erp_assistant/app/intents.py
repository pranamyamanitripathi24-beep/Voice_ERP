"""
Intent catalogue — mirrors slide 4 (Intent Classification) and slide 9
(Demo Use Cases). Each intent declares:
  - required_entities: what must be extracted before the API Gateway can act
  - is_write: whether it mutates ERP data (triggers the confirmation flow
    described on slide 6 / 8)
"""

INTENTS = {
    "check_stock": {
        "required_entities": ["item_id"],
        "is_write": False,
    },
    "get_low_stock_items": {
        "required_entities": [],
        "is_write": False,
    },
    "create_purchase_request": {
        "required_entities": ["item_id", "quantity"],
        "is_write": True,
    },
    "mark_attendance": {
        "required_entities": ["employee_id"],  # auto-filled from session if logged in
        "is_write": True,
    },
    "get_sales_report": {
        "required_entities": ["period"],
        "is_write": False,
    },
    "get_expense_summary": {
        "required_entities": ["period"],
        "is_write": False,
    },
    "get_top_expenses": {
        "required_entities": [],
        "is_write": False,
    },
    "update_stock": {
        "required_entities": ["item_id", "delta"],
        "is_write": True,
    },
    "get_attendance_summary": {
        "required_entities": ["employee_id"],
        "is_write": False,
    },
    "check_exam_eligibility": {
        "required_entities": ["employee_id"],
        "is_write": False,
    },
    "unknown": {
        "required_entities": [],
        "is_write": False,
    },
}

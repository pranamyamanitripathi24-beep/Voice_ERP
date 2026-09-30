"""
API Gateway → ERP Core — Integration Layer, slide 3/6.

- Translates a validated {intent, entities} pair into an actual ERP call.
- `format_reply` turns the raw ERP result into the natural-language string
  that gets sent to TTS (closing the loop described on slide 4/5).
- `dispatch` is also where you'd enforce RBAC per slide 6 (API Keys /
  OAuth2 / role checks) — a minimal role gate is included below as an
  example hook; wire it to your real auth/session layer in production.
"""

from app import database as erp


# Minimal example RBAC: which roles may perform which intents.
# In production this should check a verified session/JWT, not a raw string.
ROLE_PERMISSIONS = {
    "check_stock": {"field_worker", "finance", "admin", "demo"},
    "get_low_stock_items": {"field_worker", "finance", "admin", "demo"},
    "create_purchase_request": {"finance", "admin", "demo"},
    "get_sales_report": {"finance", "admin", "demo"},
    "get_expense_summary": {"finance", "admin", "demo"},
    "get_top_expenses": {"finance", "admin", "demo"},
    "mark_attendance": {"field_worker", "finance", "admin", "demo"},
    "update_stock": {"admin", "demo"},
    "get_attendance_summary": {"field_worker", "finance", "admin", "demo"},
    "check_exam_eligibility": {"field_worker", "finance", "admin", "demo"},
}


def dispatch(
    intent: str,
    entities: dict,
    role: str = "admin",
    actor_employee_id: str | None = None,
) -> dict:
    """Executes the ERP-side operation for a given intent."""
    allowed_roles = ROLE_PERMISSIONS.get(intent, set())
    if allowed_roles and role not in allowed_roles:
        return {"ok": False, "error": f"Role '{role}' is not permitted to perform '{intent}'."}
    if (
        role == "field_worker"
        and intent in {"mark_attendance", "get_attendance_summary", "check_exam_eligibility"}
        and entities.get("employee_id") != actor_employee_id
    ):
        return {"ok": False, "error": "You can only access your own attendance records."}

    if intent == "check_stock":
        stock = erp.get_stock(entities["item_id"])
        if not stock:
            return {"ok": False, "error": f"No item found with ID {entities['item_id']}"}
        return {"ok": True, **stock}

    if intent == "get_low_stock_items":
        return {"ok": True, "items": erp.get_low_stock_items()}

    if intent == "create_purchase_request":
        return erp.create_purchase_request(
            entities["item_id"], entities["quantity"], requested_by=actor_employee_id
        )

    if intent == "get_sales_report":
        return {"ok": True, **erp.get_sales_report(entities["period"])}

    if intent == "get_expense_summary":
        return {"ok": True, **erp.get_expense_report(entities["period"])}

    if intent == "get_top_expenses":
        return {"ok": True, "expenses": erp.get_top_expenses()}

    if intent == "mark_attendance":
        return erp.mark_attendance(entities["employee_id"], status="present")

    if intent == "update_stock":
        return erp.update_stock(entities["item_id"], entities["delta"])

    if intent == "get_attendance_summary":
        return erp.get_attendance_summary(entities["employee_id"])

    if intent == "check_exam_eligibility":
        return erp.check_exam_eligibility(entities["employee_id"])

    return {"ok": False, "error": f"Unhandled intent {intent}"}


def format_reply(intent: str, entities: dict, result: dict) -> str:
    """Formats the ERP result into a spoken-language sentence (feeds TTS)."""
    if not result.get("ok", False):
        return f"Sorry, that didn't work: {result.get('error', 'unknown error')}"

    if intent == "check_stock":
        return f"{result['name']} ({result['item_id']}) has {result['quantity']} units in stock."

    if intent == "get_sales_report":
        period_label = {"last_month": "last month", "this_month": "this month",
                         "today": "today"}.get(result["period"], result["period"])
        top_product = result.get("top_product")
        product_text = f" Top product: {top_product['name']}." if top_product else " No product details are available."
        change = result.get("change_percent")
        change_text = f" Change from previous period: {change:+.1f}%." if change is not None else " No previous-period sales to compare."
        return (f"Sales report for {result['period_label']} ({period_label}): "
            f"₹{result['total']:,.2f} across {result['count']} transactions."
            f" Previous period: ₹{result['previous_total']:,.2f}.{product_text}{change_text}")

    if intent == "get_low_stock_items":
        items = result.get("items", [])
        if not items:
            return "No items are currently at or below their reorder thresholds."
        summary = "; ".join(
            f"{item['name']} ({item['item_id']}): {item['quantity']} on hand, reorder at {item['reorder_threshold']}"
            for item in items[:5]
        )
        remainder = f" and {len(items) - 5} more" if len(items) > 5 else ""
        return f"{len(items)} low-stock item(s): {summary}{remainder}."

    if intent == "get_expense_summary":
        return (f"Expenses for {result['period_label']}: ₹{result['total']:,.2f} "
                f"across {result['count']} expense(s).")

    if intent == "get_top_expenses":
        expenses = result.get("expenses", [])
        if not expenses:
            return "No expenses have been recorded."
        summary = "; ".join(
            f"{expense['description']} ({expense['category']}): ₹{expense['amount']:,.2f}"
            for expense in expenses[:3]
        )
        return f"Highest expenses: {summary}."

    if intent == "create_purchase_request":
        return (f"Purchase request {result['order_id']} created for {result['quantity']} "
                f"{result['item_name']} from {result['supplier_name']}. "
                f"Estimated total: ₹{result['estimated_total']:,.2f}. Status: {result['status']}.")

    if intent == "mark_attendance":
        return f"Attendance marked as {result['status']} for {result['employee_id']} on {result['date']}."

    if intent == "update_stock":
        return (f"Updated {result['item_id']}: {result['old_quantity']} → "
                f"{result['new_quantity']} units.")

    if intent == "get_attendance_summary":
        return (f"{result['name']} has {result['present_days']} present days out of "
                f"{result['total_days']} recorded — {result['percentage']}% attendance.")

    if intent == "check_exam_eligibility":
        verdict = "eligible" if result["eligible"] else "not eligible"
        return (f"{result['name']} is {verdict} for exams: {result['percentage']}% attendance "
                f"against a {result['threshold']}% requirement.")

    return "Done."

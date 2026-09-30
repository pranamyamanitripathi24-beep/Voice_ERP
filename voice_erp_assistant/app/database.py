"""
ERP Core (Database & Business Logic) — Integration Layer, slide 3/6.

This is a mock ERP built on SQLite so the whole pipeline runs with zero
external dependencies. In production you would swap this module for calls
into Odoo's XML-RPC API or a real Postgres-backed ERP, while keeping the
same function signatures — that's the whole point of the Integration Layer
being a "bridge": everything above this file (NLU, Dialog Manager, API
Gateway) never needs to change.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "erp_mock.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn, table: str, column: str, definition: str):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db(seed: bool = True):
    """Creates tables and (optionally) seeds demo data. Safe to call repeatedly."""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                email TEXT,
                phone TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                item_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                reorder_threshold INTEGER NOT NULL DEFAULT 10,
                supplier_id INTEGER REFERENCES suppliers(supplier_id),
                unit_cost REAL NOT NULL DEFAULT 0
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL  -- 'field_worker', 'finance', 'admin'
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE(employee_id, date)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_date TEXT NOT NULL,
                amount REAL NOT NULL,
                item_id TEXT REFERENCES inventory(item_id),
                quantity INTEGER NOT NULL DEFAULT 1
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_date TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL CHECK (amount >= 0),
                employee_id TEXT REFERENCES employees(employee_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS purchase_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
                status TEXT NOT NULL DEFAULT 'requested',
                created_at TEXT NOT NULL,
                requested_by TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS purchase_order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES purchase_orders(order_id),
                item_id TEXT NOT NULL REFERENCES inventory(item_id),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_cost REAL NOT NULL CHECK (unit_cost >= 0)
            )
        """)

        _ensure_column(conn, "inventory", "supplier_id", "INTEGER REFERENCES suppliers(supplier_id)")
        _ensure_column(conn, "inventory", "unit_cost", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "sales", "item_id", "TEXT REFERENCES inventory(item_id)")
        _ensure_column(conn, "sales", "quantity", "INTEGER NOT NULL DEFAULT 1")

        if seed:
            c.executemany(
                "INSERT OR IGNORE INTO suppliers (name, email, phone) VALUES (?, ?, ?)",
                [
                    ("Apex Industrial Supply", "orders@apex.example", "+1-555-0101"),
                    ("Circuit Source", "sales@circuitsource.example", "+1-555-0102"),
                ],
            )
            supplier_ids = {
                row["name"]: row["supplier_id"]
                for row in c.execute("SELECT supplier_id, name FROM suppliers")
            }
            c.execute("SELECT COUNT(*) FROM inventory")
            if c.fetchone()[0] == 0:
                c.executemany(
                    "INSERT INTO inventory (item_id, name, quantity, reorder_threshold, supplier_id, unit_cost) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        ("P-101", "Steel Bolt 10mm", 540, 100, supplier_ids["Apex Industrial Supply"], 2.5),
                        ("P-102", "Hydraulic Valve", 8, 20, supplier_ids["Apex Industrial Supply"], 85.0),
                        ("P-103", "Circuit Board Rev C", 132, 50, supplier_ids["Circuit Source"], 42.0),
                    ],
                )
            for item_id, supplier_name, unit_cost in [
                ("P-101", "Apex Industrial Supply", 2.5),
                ("P-102", "Apex Industrial Supply", 85.0),
                ("P-103", "Circuit Source", 42.0),
            ]:
                c.execute(
                    "UPDATE inventory SET supplier_id = ?, unit_cost = ? "
                    "WHERE item_id = ? AND supplier_id IS NULL",
                    (supplier_ids[supplier_name], unit_cost, item_id),
                )
            c.execute(
                "UPDATE inventory SET supplier_id = ? WHERE supplier_id IS NULL",
                (next(iter(supplier_ids.values())),),
            )
            c.execute("SELECT COUNT(*) FROM employees")
            if c.fetchone()[0] == 0:
                c.executemany(
                    "INSERT INTO employees (employee_id, name, role) VALUES (?, ?, ?)",
                    [
                        ("E-001", "Asha Rao", "field_worker"),
                        ("E-002", "Vikram Nair", "finance"),
                        ("E-003", "Priya Menon", "admin"),
                    ],
                )
            c.execute("SELECT COUNT(*) FROM attendance")
            if c.fetchone()[0] == 0:
                # Seed ~20 days of attendance history per employee so
                # percentage-based queries (attendance %, exam eligibility)
                # have something real to compute against.
                today = date.today()
                rows = []
                for emp_id, absent_every in [("E-001", 7), ("E-002", 4), ("E-003", 20)]:
                    for i in range(20, 0, -1):
                        day = (today - timedelta(days=i)).isoformat()
                        status = "absent" if i % absent_every == 0 else "present"
                        rows.append((emp_id, day, status))
                c.executemany(
                    "INSERT OR IGNORE INTO attendance (employee_id, date, status) VALUES (?, ?, ?)",
                    rows,
                )

            c.execute("SELECT COUNT(*) FROM sales")
            if c.fetchone()[0] == 0:
                today = date.today()
                last_month = today.replace(day=1) - timedelta(days=1)
                c.executemany(
                    "INSERT INTO sales (sale_date, amount, item_id, quantity) VALUES (?, ?, ?, ?)",
                    [
                        (last_month.replace(day=5).isoformat(), 125000.0, "P-101", 40),
                        (last_month.replace(day=15).isoformat(), 98000.0, "P-103", 18),
                        (last_month.replace(day=25).isoformat(), 176500.0, "P-101", 60),
                        (today.isoformat(), 42000.0, "P-102", 12),
                    ],
                )
            c.execute("SELECT COUNT(*) FROM expenses")
            if c.fetchone()[0] == 0:
                today = date.today()
                last_month = today.replace(day=1) - timedelta(days=1)
                c.executemany(
                    "INSERT INTO expenses (expense_date, category, description, amount, employee_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [
                        (today.replace(day=1).isoformat(), "Travel", "Local supplier visits", 4500.0, "E-002"),
                        (today.isoformat(), "Operations", "Workshop supplies", 1800.0, "E-003"),
                        (last_month.replace(day=5).isoformat(), "Utilities", "Warehouse electricity", 7200.0, "E-003"),
                        (last_month.replace(day=15).isoformat(), "Travel", "Regional delivery mileage", 3200.0, "E-002"),
                    ],
                )


# ---------- Read operations ----------

def get_stock(item_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM inventory WHERE item_id = ? COLLATE NOCASE", (item_id,)
        ).fetchone()
        return dict(row) if row else None


def get_inventory(search: str = "", low_stock_only: bool = False):
    """Lists inventory, optionally filtered by name/ID and reorder level."""
    query = "SELECT * FROM inventory WHERE 1 = 1"
    params = []
    if search.strip():
        query += " AND (name LIKE ? COLLATE NOCASE OR item_id LIKE ? COLLATE NOCASE)"
        term = f"%{search.strip()}%"
        params.extend((term, term))
    if low_stock_only:
        query += " AND quantity <= reorder_threshold"
    query += " ORDER BY name"
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_employee(employee_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT employee_id, name, role FROM employees WHERE employee_id = ? COLLATE NOCASE",
            (employee_id,),
        ).fetchone()
        return dict(row) if row else None


def get_dashboard_summary(employee_id: str | None = None, include_sales: bool = True):
    """Returns compact operational KPIs for the dashboard."""
    today = date.today()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    with get_conn() as conn:
        inventory = conn.execute(
            "SELECT COUNT(*) AS product_count, COALESCE(SUM(quantity), 0) AS total_units "
            "FROM inventory"
        ).fetchone()
        low_stock = conn.execute(
            "SELECT * FROM inventory WHERE quantity <= reorder_threshold ORDER BY quantity, name"
        ).fetchall()
        summary = {
            "product_count": inventory["product_count"],
            "total_units": inventory["total_units"],
            "low_stock_count": len(low_stock),
            "low_stock_items": [dict(row) for row in low_stock],
        }
        if include_sales:
            current_sales = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM sales WHERE sale_date BETWEEN ? AND ?",
                (first_of_month.isoformat(), today.isoformat()),
            ).fetchone()["total"]
            previous_sales = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM sales WHERE sale_date BETWEEN ? AND ?",
                (last_month_start.isoformat(), last_month_end.isoformat()),
            ).fetchone()["total"]
            summary["sales_this_month"] = current_sales
            summary["sales_last_month"] = previous_sales
        if employee_id:
            attendance = conn.execute(
                "SELECT COUNT(*) AS total_days, "
                "SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present_days "
                "FROM attendance WHERE employee_id = ?",
                (employee_id,),
            ).fetchone()
            total_days = attendance["total_days"]
            present_days = attendance["present_days"] or 0
            summary["attendance_percentage"] = (
                round(present_days / total_days * 100, 1) if total_days else 0.0
            )
        return summary


def get_context_options():
    """Returns safe display options for the web assistant's context selector."""
    with get_conn() as conn:
        employees = conn.execute(
            "SELECT employee_id, name FROM employees ORDER BY name"
        ).fetchall()
        inventory = conn.execute(
            "SELECT item_id, name FROM inventory ORDER BY name"
        ).fetchall()
        return {
            "employees": [dict(row) for row in employees],
            "inventory": [dict(row) for row in inventory],
            "sales_periods": [
                {"value": "today", "label": "Today"},
                {"value": "this month", "label": "This month"},
                {"value": "last month", "label": "Last month"},
            ],
        }


def _period_bounds(period: str, today: date):
    first_of_month = today.replace(day=1)
    if period == "today":
        return today, today
    if period == "last_month":
        end = first_of_month - timedelta(days=1)
        return end.replace(day=1), end
    return first_of_month, today


def get_sales_report(period: str):
    """Build sales totals, top product, transactions, and prior-period change."""
    today = date.today()
    start, end = _period_bounds(period, today)
    if period == "today":
        previous_start = previous_end = today - timedelta(days=1)
    elif period == "last_month":
        previous_end = start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
    else:
        previous_end = start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT s.id, s.sale_date, s.amount, s.item_id, s.quantity, i.name AS item_name "
            "FROM sales s LEFT JOIN inventory i ON i.item_id = s.item_id "
            "WHERE s.sale_date BETWEEN ? AND ? ORDER BY s.sale_date, s.id",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        total = sum(r["amount"] for r in rows)
        previous_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM sales WHERE sale_date BETWEEN ? AND ?",
            (previous_start.isoformat(), previous_end.isoformat()),
        ).fetchone()[0]
        top_product = conn.execute(
            "SELECT s.item_id, i.name, SUM(s.amount) AS sales_amount, "
            "SUM(s.quantity) AS units_sold FROM sales s "
            "JOIN inventory i ON i.item_id = s.item_id "
            "WHERE s.sale_date BETWEEN ? AND ? GROUP BY s.item_id, i.name "
            "ORDER BY sales_amount DESC, i.name LIMIT 1",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        change_percent = (
            round((total - previous_total) / previous_total * 100, 1)
            if previous_total else None
        )
        return {"period": period, "start": start.isoformat(), "end": end.isoformat(),
                "period_label": start.strftime("%B %Y") if period != "today" else f"{start.strftime('%B')} {start.day}, {start.year}",
                "total": total, "count": len(rows),
                "previous_total": previous_total,
                "previous_period_label": previous_start.strftime("%B %Y"),
                "change_percent": change_percent,
                "top_product": dict(top_product) if top_product else None,
                "transactions": [dict(row) for row in rows]}


def get_low_stock_items():
    return get_inventory(low_stock_only=True)


def get_expense_report(period: str):
    today = date.today()
    start, end = _period_bounds(period, today)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, expense_date, category, description, amount, employee_id "
            "FROM expenses WHERE expense_date BETWEEN ? AND ? "
            "ORDER BY expense_date DESC, id DESC",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        total = sum(row["amount"] for row in rows)
        return {
            "period": period,
            "period_label": start.strftime("%B %Y") if period != "today" else start.isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total": total,
            "count": len(rows),
            "expenses": [dict(row) for row in rows],
        }


def get_top_expenses(limit: int = 5):
    limit = max(1, min(int(limit), 50))
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, expense_date, category, description, amount, employee_id "
            "FROM expenses ORDER BY amount DESC, expense_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def create_purchase_request(item_id: str, quantity: int, requested_by: str | None = None):
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Purchase quantity must be a whole number."}
    if quantity <= 0:
        return {"ok": False, "error": "Purchase quantity must be greater than zero."}

    with get_conn() as conn:
        item = conn.execute(
            "SELECT i.item_id, i.name, i.supplier_id, i.unit_cost, s.name AS supplier_name "
            "FROM inventory i LEFT JOIN suppliers s ON s.supplier_id = i.supplier_id "
            "WHERE i.item_id = ? COLLATE NOCASE",
            (item_id,),
        ).fetchone()
        if not item:
            return {"ok": False, "error": f"Unknown item_id {item_id}."}
        if not item["supplier_id"]:
            return {"ok": False, "error": f"No supplier is assigned to {item['name']}."}

        created_at = datetime.now().isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO purchase_orders (supplier_id, status, created_at, requested_by) "
            "VALUES (?, 'requested', ?, ?)",
            (item["supplier_id"], created_at, requested_by),
        )
        order_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO purchase_order_items (order_id, item_id, quantity, unit_cost) "
            "VALUES (?, ?, ?, ?)",
            (order_id, item["item_id"], quantity, item["unit_cost"]),
        )
        return {
            "ok": True,
            "order_id": order_id,
            "status": "requested",
            "created_at": created_at,
            "supplier_name": item["supplier_name"],
            "item_id": item["item_id"],
            "item_name": item["name"],
            "quantity": quantity,
            "unit_cost": item["unit_cost"],
            "estimated_total": round(quantity * item["unit_cost"], 2),
        }


def get_attendance_summary(employee_id: str):
    """Answers 'How much attendance do I have' / 'Show my attendance' style
    queries — computes a percentage over all recorded days, not just today."""
    with get_conn() as conn:
        emp = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        if not emp:
            return {"ok": False, "error": f"Unknown employee_id {employee_id}"}
        rows = conn.execute(
            "SELECT status FROM attendance WHERE employee_id = ?", (employee_id,)
        ).fetchall()
        total = len(rows)
        present = sum(1 for r in rows if r["status"] == "present")
        pct = round((present / total) * 100, 1) if total else 0.0
        return {"ok": True, "employee_id": employee_id, "name": emp["name"],
                "total_days": total, "present_days": present, "percentage": pct}


def check_exam_eligibility(employee_id: str, threshold: float = 75.0):
    """Answers 'Am I eligible for exams based on attendance' — applies a
    simple threshold rule on top of get_attendance_summary. In a real ERP
    this threshold would come from an institution's policy table."""
    summary = get_attendance_summary(employee_id)
    if not summary.get("ok"):
        return summary
    eligible = summary["percentage"] >= threshold
    return {**summary, "threshold": threshold, "eligible": eligible}


# ---------- Write operations (require confirmation upstream) ----------

def mark_attendance(employee_id: str, status: str = "present", day: str = None):
    day = day or date.today().isoformat()
    with get_conn() as conn:
        emp = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        if not emp:
            return {"ok": False, "error": f"Unknown employee_id {employee_id}"}
        conn.execute(
            """INSERT INTO attendance (employee_id, date, status) VALUES (?, ?, ?)
               ON CONFLICT(employee_id, date) DO UPDATE SET status=excluded.status""",
            (employee_id, day, status),
        )
        return {"ok": True, "employee_id": employee_id, "date": day, "status": status}


def update_stock(item_id: str, delta: int):
    """delta can be negative (consumption) or positive (restock)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM inventory WHERE item_id = ? COLLATE NOCASE", (item_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": f"Unknown item_id {item_id}"}
        new_qty = max(0, row["quantity"] + delta)
        conn.execute(
            "UPDATE inventory SET quantity = ? WHERE item_id = ?", (new_qty, row["item_id"])
        )
        return {"ok": True, "item_id": row["item_id"], "old_quantity": row["quantity"],
                "new_quantity": new_qty}


if __name__ == "__main__":
    init_db()
    print(f"Initialized mock ERP DB at {DB_PATH}")

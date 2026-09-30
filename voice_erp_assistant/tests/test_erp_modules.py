import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import database
from app.dialog_manager import handle_utterance
from app.nlu import classify
from app.reporting import generate_sales_report


class ERPModuleTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = database.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp_dir.name) / "erp-test.db"
        database.init_db()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp_dir.cleanup()

    def test_schema_reinitializes_and_reports_seed_data(self):
        database.init_db()
        with database.get_conn() as conn:
            tables = {row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
        self.assertTrue({"suppliers", "purchase_orders", "purchase_order_items", "expenses"} <= tables)
        self.assertEqual(database.get_expense_report("last_month")["total"], 10400)
        self.assertEqual(database.get_sales_report("this_month")["top_product"]["name"], "Hydraulic Valve")

    def test_legacy_schema_upgrades_without_losing_sales(self):
        legacy_path = Path(self.temp_dir.name) / "legacy.db"
        database.DB_PATH = legacy_path
        conn = sqlite3.connect(legacy_path)
        conn.executescript("""
            CREATE TABLE inventory (
                item_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                quantity INTEGER NOT NULL, reorder_threshold INTEGER NOT NULL DEFAULT 10
            );
            CREATE TABLE employees (
                employee_id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL
            );
            CREATE TABLE attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL,
                date TEXT NOT NULL, status TEXT NOT NULL, UNIQUE(employee_id, date)
            );
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT, sale_date TEXT NOT NULL, amount REAL NOT NULL
            );
            INSERT INTO inventory VALUES ('P-102', 'Hydraulic Valve', 8, 20);
            INSERT INTO employees VALUES ('E-001', 'Asha Rao', 'field_worker');
            INSERT INTO sales (sale_date, amount) VALUES ('2026-09-28', 42000);
        """)
        conn.commit()
        conn.close()

        database.init_db()
        with database.get_conn() as conn:
            sales_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sales)")}
            sale = conn.execute("SELECT amount, item_id, quantity FROM sales").fetchone()
            inventory = conn.execute(
                "SELECT supplier_id, unit_cost FROM inventory WHERE item_id = 'P-102'"
            ).fetchone()
        self.assertTrue({"item_id", "quantity"} <= sales_columns)
        self.assertEqual(sale["amount"], 42000)
        self.assertEqual(sale["quantity"], 1)
        self.assertIsNotNone(inventory["supplier_id"])
        self.assertEqual(inventory["unit_cost"], 85)

    def test_requested_voice_commands_classify(self):
        commands = {
            "Which items are low in stock?": "get_low_stock_items",
            "Create a purchase request for hydraulic valves": "create_purchase_request",
            "How much did we spend this month?": "get_expense_summary",
            "What was our total expenditure last month?": "get_expense_summary",
            "Show me the highest expenses": "get_top_expenses",
            "Generate this month's sales report": "get_sales_report",
        }
        for command, expected_intent in commands.items():
            with self.subTest(command=command):
                self.assertEqual(classify(command).intent, expected_intent)

    def test_purchase_request_requires_quantity_and_confirmation(self):
        session_id = "purchase-test-session"
        first = handle_utterance(
            session_id, "Create a purchase request for hydraulic valves", role="admin"
        )
        self.assertTrue(first["awaiting_clarification"])
        self.assertIn("How many units", first["reply"])

        second = handle_utterance(session_id, "24 units", role="admin")
        self.assertTrue(second["awaiting_confirmation"])
        self.assertIn("24 units", second["reply"])

        confirmed = handle_utterance(session_id, "yes", role="admin")
        self.assertTrue(confirmed["result"]["ok"])
        self.assertEqual(confirmed["result"]["quantity"], 24)

    def test_csv_and_pdf_sales_exports(self):
        report = database.get_sales_report("this_month")
        csv_data, csv_type = generate_sales_report(report, "csv")
        pdf_data, pdf_type = generate_sales_report(report, "pdf")
        self.assertTrue(csv_type.startswith("text/csv"))
        self.assertIn(b"Hydraulic Valve", csv_data)
        self.assertEqual(pdf_type, "application/pdf")
        self.assertTrue(pdf_data.startswith(b"%PDF"))
        self.assertIn(b"%%EOF", pdf_data[-32:])


if __name__ == "__main__":
    unittest.main()
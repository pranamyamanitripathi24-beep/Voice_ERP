"""
Text-only, dependency-free demo of the full pipeline (skips STT/TTS/mic).
Runs the exact 3 scenarios from slide 9 automatically, then drops into an
interactive prompt so you can try your own commands.

Usage:
    python demo.py
"""

from app import database
from app.dialog_manager import handle_utterance

SEPARATOR = "-" * 60


def run_turn(session_id: str, text: str, employee_id: str = None):
    print(f"You: {text}")
    outcome = handle_utterance(session_id, text, employee_id)
    print(f"Assistant: {outcome['reply']}")
    return outcome


def scripted_demo():
    database.init_db(seed=True)

    print(SEPARATOR)
    print("USE CASE 1: Inventory Query")
    print(SEPARATOR)
    run_turn("demo-inventory", "Show stock for item P-102")

    print()
    print(SEPARATOR)
    print("USE CASE 2: HR - Attendance Logging (with confirmation)")
    print(SEPARATOR)
    run_turn("demo-hr", "Mark my attendance", employee_id="E-001")
    run_turn("demo-hr", "yes")  # confirm the write operation

    print()
    print(SEPARATOR)
    print("USE CASE 3: Finance - Sales Report")
    print(SEPARATOR)
    run_turn("demo-finance", "Get total sales from last month")

    print()
    print(SEPARATOR)
    print("BONUS: Ambiguous command -> clarification loop (slide 8 mitigation)")
    print(SEPARATOR)
    run_turn("demo-clarify", "Check stock")           # missing item_id
    run_turn("demo-clarify", "P-101")                  # user supplies it

    print()
    print(SEPARATOR)
    print("USE CASE 4: Attendance % and exam eligibility (rule-based NLU limits)")
    print(SEPARATOR)
    print("NOTE: with the default NLU_ENGINE=rule these WILL fail to be understood")
    print("      -- that's expected, and exactly the limitation discussed in the")
    print("      'Is it actually AI?' section of the README. Set NLU_ENGINE=llm")
    print("      (with Ollama installed) to see these work correctly.")
    print(SEPARATOR)
    run_turn("demo-attendance", "How much attendance do I have?", employee_id="E-001")
    run_turn("demo-attendance2", "Am I eligible for exams based on attendance?", employee_id="E-002")


def interactive():
    print()
    print(SEPARATOR)
    print("Interactive mode — type commands, 'quit' to exit.")
    print("Try: 'check stock for P-103', 'mark my attendance', "
          "'get total sales from last month', 'remove 5 units from P-101'")
    print(SEPARATOR)
    session_id = "interactive-session"
    employee_id = "E-001"
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("quit", "exit"):
            break
        if not text:
            continue
        outcome = handle_utterance(session_id, text, employee_id)
        print(f"Assistant: {outcome['reply']}")


if __name__ == "__main__":
    scripted_demo()
    interactive()

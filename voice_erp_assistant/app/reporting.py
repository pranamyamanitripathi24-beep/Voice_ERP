"""CSV and PDF exports for ERP reports."""

import csv
import io


def _sales_csv(report: dict) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    top_product = report.get("top_product")
    writer.writerow(["SALES REPORT"])
    writer.writerow(["Period", report["period_label"]])
    writer.writerow(["Total Sales (INR)", report["total"]])
    writer.writerow(["Transactions", report["count"]])
    writer.writerow(["Top Product", top_product["name"] if top_product else "Not available"])
    writer.writerow(["Previous Period Sales (INR)", report["previous_total"]])
    writer.writerow(["Change (%)", report["change_percent"] if report["change_percent"] is not None else "N/A"])
    writer.writerow([])
    writer.writerow(["Date", "Item ID", "Product", "Quantity", "Amount"])
    for row in report["transactions"]:
        writer.writerow([
            row["sale_date"], row["item_id"] or "", row["item_name"] or "Unspecified",
            row["quantity"], row["amount"],
        ])
    return output.getvalue().encode("utf-8-sig")


def _sales_pdf(report: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=landscape(letter),
        rightMargin=0.55 * inch, leftMargin=0.55 * inch,
        topMargin=0.55 * inch, bottomMargin=0.55 * inch,
    )
    styles = getSampleStyleSheet()
    top_product = report.get("top_product")
    change = report["change_percent"]
    summary_rows = [
        ["Period", report["period_label"], "Total sales", f"₹{report['total']:,.2f}"],
        ["Transactions", str(report["count"]), "Previous period", f"₹{report['previous_total']:,.2f}"],
        ["Top product", top_product["name"] if top_product else "Not available",
         "Change", f"{change:+.1f}%" if change is not None else "N/A"],
    ]
    transaction_rows = [["Date", "Item ID", "Product", "Quantity", "Amount"]]
    transaction_rows.extend([
        [row["sale_date"], row["item_id"] or "", row["item_name"] or "Unspecified",
         str(row["quantity"]), f"₹{row['amount']:,.2f}"]
        for row in report["transactions"]
    ])
    story = [
        Paragraph("SALES REPORT", styles["Title"]),
        Paragraph(f"Period: {report['period_label']} ({report['start']} to {report['end']})", styles["Normal"]),
        Spacer(1, 14),
        Table(summary_rows, colWidths=[1.25 * inch, 2.5 * inch, 1.35 * inch, 2.2 * inch]),
        Spacer(1, 18),
        Paragraph("Transactions", styles["Heading2"]),
        Table(transaction_rows, repeatRows=1, colWidths=[1.4 * inch, 1.1 * inch, 4.2 * inch, 1.0 * inch, 1.4 * inch]),
    ]
    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#153d35")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dce4df")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f7f3")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ])
    story[3].setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f7f3")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#dce4df")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story[6].setStyle(table_style)
    document.build(story)
    return output.getvalue()


def generate_sales_report(report: dict, output_format: str) -> tuple[bytes, str]:
    if output_format == "csv":
        return _sales_csv(report), "text/csv; charset=utf-8"
    if output_format == "pdf":
        return _sales_pdf(report), "application/pdf"
    raise ValueError("output_format must be csv or pdf")
import csv
import io
import json

from fpdf import FPDF


def build_json_export(meta_title: str, result: dict) -> bytes:
    return json.dumps({"title": meta_title, **result}, indent=2).encode("utf-8")


def build_csv_export(meta_title: str, result: dict) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Field", "Value"])
    writer.writerow(["Title (original)", meta_title])
    writer.writerow(["Tags", ", ".join(result.get("tags", []))])
    writer.writerow(["Suggested titles", " | ".join(result.get("titles", []))])
    writer.writerow(["Description", result.get("description", "")])
    writer.writerow(["Hashtags", " ".join(result.get("hashtags", []))])
    writer.writerow([
        "Chapters",
        " | ".join(f"{c.get('timestamp', '')} {c.get('title', '')}" for c in result.get("chapters", [])),
    ])
    writer.writerow(["Suggestions", " | ".join(result.get("suggestions", []))])
    hook = result.get("hook_analysis", {})
    writer.writerow(["Hook verdict", hook.get("verdict", "")])
    writer.writerow(["Hook reasoning", hook.get("reasoning", "")])
    sentiment = result.get("comment_sentiment", {})
    writer.writerow(["Comment sentiment summary", sentiment.get("summary", "")])
    return buf.getvalue().encode("utf-8")


def build_pdf_export(meta_title: str, result: dict) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 10, "YouTube SEO Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 8, meta_title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    def section(heading: str, body: str) -> None:
        if not body:
            return
        pdf.set_font("Helvetica", "B", 13)
        pdf.multi_cell(0, 8, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, body, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    section("Suggested Titles", "\n".join(f"- {t}" for t in result.get("titles", [])))
    section("Tags", ", ".join(result.get("tags", [])))
    section("Hashtags", " ".join(result.get("hashtags", [])))
    section("Description", result.get("description", ""))
    section(
        "Chapters",
        "\n".join(f"{c.get('timestamp', '')}  {c.get('title', '')}" for c in result.get("chapters", [])),
    )
    section("Suggestions", "\n".join(f"- {s}" for s in result.get("suggestions", [])))
    hook = result.get("hook_analysis", {})
    section("Hook Analysis", f"Verdict: {hook.get('verdict', '')}\n{hook.get('reasoning', '')}")
    sentiment = result.get("comment_sentiment", {})
    section("Comment Sentiment", sentiment.get("summary", ""))

    return bytes(pdf.output())

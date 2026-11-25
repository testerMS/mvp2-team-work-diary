"""report.md 를 인쇄·공유하기 좋은 report.html 로 바꾼다.

사용법: python scripts/render_html.py output/2026-11-24
"""
import html
import sys
from pathlib import Path

STYLE = """
body{font-family:'Malgun Gothic','맑은 고딕',sans-serif;max-width:820px;margin:32px auto;padding:0 16px;color:#1d2733;background:#fff;line-height:1.65}
h1{text-align:center;font-size:26px;border-bottom:3px double #1f4e79;padding-bottom:12px}
h2{font-size:17px;color:#1f4e79;border-left:5px solid #1f4e79;padding-left:9px;margin:28px 0 8px}
p{margin:3px 0}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border:1px solid #b8c4d0;padding:6px 8px;text-align:left;vertical-align:top}th{background:#eaf0f6;white-space:nowrap}
.긴급{color:#b3261e;font-weight:700}.높음{color:#9a5b00;font-weight:700}
@media print{body{margin:0}h2{break-after:avoid}tr{break-inside:avoid}}
"""


def render(md):
    out, rows = [], []

    def flush():
        if rows:
            out.append("<table><tr>" + "".join(f"<th>{c}</th>" for c in rows[0]) + "</tr>")
            for r in rows[1:]:
                out.append("<tr>" + "".join(f'<td class="{c}">{c}</td>' if c in ("긴급", "높음") else f"<td>{c}</td>" for c in r) + "</tr>")
            out.append("</table>")
            rows.clear()
    for line in md.splitlines():
        if line.startswith("|"):
            cells = [html.escape(c.strip()) for c in line.strip().strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                rows.append(cells)
            continue
        flush()
        text = html.escape(line.strip())
        if line.startswith("## "):
            out.append(f"<h2>{text[3:]}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{text[2:]}</h1>")
        elif text:
            indent = len(line) - len(line.lstrip())
            out.append(f'<p style="margin-left:{indent * 8}px">{text}</p>')
    flush()
    return ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>일일 업무보고</title><style>{STYLE}</style></head><body>" + "\n".join(out) + "</body></html>")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    argv = sys.argv[1:] if argv is None else argv
    folder = Path(argv[0]) if argv else Path(".")
    if not (folder / "report.md").exists():
        print(f"{folder} 에 report.md 가 없습니다.")
        return 2
    (folder / "report.html").write_text(render((folder / "report.md").read_text(encoding="utf-8-sig")), encoding="utf-8")
    print(f"[HTML] {folder / 'report.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Converts STRATEGY.md → STRATEGY.html and opens it for printing to PDF.
Run from the project root:
    python strategies/spy_intraday_short/generate_pdf.py
"""

import os
import webbrowser
import markdown

_HERE     = os.path.dirname(os.path.abspath(__file__))
md_path   = os.path.join(_HERE, "STRATEGY.md")
html_path = os.path.join(_HERE, "STRATEGY.html")

with open(md_path) as f:
    md_text = f.read()

html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SPY Intraday Afternoon Short — Strategy Documentation</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    font-size: 13px; line-height: 1.7; color: #1a1a1a;
    max-width: 860px; margin: 40px auto; padding: 0 30px 60px;
  }}
  h1 {{ font-size: 26px; border-bottom: 2px solid #1a1a1a; padding-bottom: 8px; margin-top: 30px; }}
  h2 {{ font-size: 20px; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 36px; color: #222; }}
  h3 {{ font-size: 15px; margin-top: 24px; color: #333; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 12.5px; }}
  th, td {{ border: 1px solid #ccc; padding: 7px 12px; text-align: left; }}
  th {{ background: #f4f4f4; font-weight: 600; }}
  tr:nth-child(even) {{ background: #fafafa; }}
  code {{ background: #f4f4f4; padding: 1px 5px; border-radius: 3px;
           font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }}
  pre {{ background: #f4f4f4; border-left: 3px solid #555; padding: 12px 16px;
          border-radius: 4px; overflow-x: auto; font-size: 12px; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 4px solid #0066cc; background: #f0f6ff;
                margin: 16px 0; padding: 10px 16px; border-radius: 0 4px 4px 0; }}
  blockquote p {{ margin: 0; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 28px 0; }}
  @media print {{
    body {{ margin: 0; padding: 20px; max-width: 100%; }}
    pre, table {{ page-break-inside: avoid; }}
  }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

with open(html_path, "w") as f:
    f.write(html)

print(f"[done] HTML written → {html_path}")
print("\nTo save as PDF:  open in browser → Cmd+P → Save as PDF")
webbrowser.open(f"file://{html_path}")

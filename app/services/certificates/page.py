"""The HTML page a phone opens when it scans a certificate's QR."""
from __future__ import annotations

from html import escape

_STYLE = (
    ":root{color-scheme:light dark;--bg:#f4f5f7;--fg:#1f2328;--card:#fff;--muted:#6b7280;"
    "--line:#eceef1}@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;"
    "--card:#161b22;--muted:#9aa4b2;--line:#30363d}}*{box-sizing:border-box}"
    "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;"
    "padding:24px 16px;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"
    "background:var(--bg);color:var(--fg)}.card{width:100%;max-width:440px;"
    "background:var(--card);border-radius:16px;padding:32px 24px;text-align:center;"
    "box-shadow:0 8px 40px rgba(0,0,0,.12)}.badge{width:68px;height:68px;border-radius:50%;"
    "margin:0 auto 16px;display:flex;align-items:center;justify-content:center;font-size:34px;"
    "color:#fff;font-weight:700}.ok .badge{background:#3645ff}.bad .badge{background:#d64545}"
    "h1{font-size:21px;margin:0 0 8px}.muted{color:var(--muted);font-size:14px;"
    "line-height:1.5;margin:0 0 20px}.row{display:flex;justify-content:space-between;gap:16px;"
    "padding:11px 2px;border-top:1px solid var(--line);font-size:14px;text-align:left}"
    ".k{color:var(--muted)}.v{font-weight:600;text-align:right}"
)


def _shell(title: str, inner: str, status: str) -> str:
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{escape(title)}</title><style>{_STYLE}</style></head><body>"
            f"<section class='card {status}'>{inner}</section></body></html>")


def verify_page(data: dict | None) -> str:
    """``data`` is :func:`.verification.verify`'s answer, or ``None`` for not found."""
    if data is None:
        return _shell("Certificate not found", "<div class='badge'>✕</div>"
                      "<h1>Certificate not found</h1><p class='muted'>This certificate "
                      "number was not issued by AI Academy Asia, or it was withdrawn.</p>",
                      "bad")
    rows = [("Certificate no.", data["cert_number"]), ("Issued", data["issued_at"][:10])]
    if not data.get("details_hidden"):
        title = data.get("course_title") or {}
        rows = [("Name", data.get("student_name")),
                ("Programme", title.get("en") or title.get("mn"))] + rows
    body = "".join(f"<div class='row'><span class='k'>{escape(k)}</span>"
                   f"<span class='v'>{escape(str(v or ''))}</span></div>" for k, v in rows)
    return _shell("Certificate verified", "<div class='badge'>✓</div>"
                  "<h1>Verified certificate</h1><p class='muted'>This certificate was "
                  f"issued by AI Academy Asia.</p>{body}", "ok")

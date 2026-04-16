#!/usr/bin/env python3
"""
סקריפט סריקת חקיקה — משרד עו"ד גיל מזור
מריץ Claude API לזיהוי שינויי חקיקה במקרקעין
שולח מייל לאישור לפני פרסום

הרצה: python scan_legislation.py [--full] [--year YYYY]
  --full       סרוק 10 שנים אחרונות (הרצה ראשונה)
  --year YYYY  סרוק שנה ספציפית
"""

import os
import sys
import json
import datetime
import argparse
import smtplib
import urllib.request
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ══ הגדרות ══
CLAUDE_MODEL   = "claude-sonnet-4-20250514"
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
OUTPUT_FILE    = Path(__file__).parent.parent / "pending_legislation.json"

LAWS = [
    "חוק המקרקעין, תשכ\"ט-1969",
    "חוק המכר (דירות), תשל\"ג-1973",
    "חוק בתי משותפים (חלק ו' לחוק המקרקעין)",
    "חוק הגנת הדייר, תשל\"ב-1972",
    "חוק שכירות ושאילה, תשל\"א-1971",
    "חוק פינוי ובינוי, תשס\"ו-2006",
    "חוק התכנון והבניה, תשכ\"ה-1965",
    "חוק מס שבח מקרקעין, תשכ\"ג-1963",
    "חוק חוזים (חלק כללי), תשל\"ג-1973",
    "תקנות המקרקעין (ניהול ורישום), תש\"ל-1969",
    "חוק עסקאות מקרקעין (קידום רישום), תשע\"ב-2011",
]

def get_claude_key():
    key = os.environ.get("CLAUDE_API_KEY", "")
    if not key:
        raise ValueError("CLAUDE_API_KEY environment variable not set")
    return key

def get_email_config():
    return {
        "smtp_host":  os.environ.get("SMTP_HOST",  "smtp.gmail.com"),
        "smtp_port":  int(os.environ.get("SMTP_PORT", "587")),
        "smtp_user":  os.environ.get("SMTP_USER",  ""),
        "smtp_pass":  os.environ.get("SMTP_PASS",  ""),
        "to_email":   os.environ.get("TO_EMAIL",   "office@678.co.il"),
        "admin_url":  os.environ.get("ADMIN_URL",  "https://678.co.il/admin.html"),
    }

def call_claude(prompt: str, max_tokens: int = 4000) -> str:
    key = get_claude_key()
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")
    req = urllib.request.Request(
        CLAUDE_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["content"][0]["text"]

def build_prompt(period_desc: str, years_range: str) -> str:
    laws_list = "\n".join(f"{i+1}. {law}" for i, law in enumerate(LAWS))
    return f"""אתה עוזר משפטי ישראלי לעורך דין המתמחה במקרקעין.

עליך לסקור שינויי חקיקה ישראלית רלוונטיים מהתקופה: {period_desc}.

חוקים לסריקה:
{laws_list}

הנחיות:
- כלול תיקוני חוק, תקנות חדשות, צווים, הוראות שעה ופסיקה מנחה של בית המשפט העליון.
- התמקד בשינויים מהותיים הנוגעים לזכויות רוכשי דירות, בעלי נכסים, שוכרים ובתים משותפים.
- אם {period_desc} כולל עשר שנים — בחר 8-12 שינויים משמעותיים ביותר.
- אם {period_desc} הוא שבוע אחד — כלול הכל, גם אם אין שינויים (ציין אז מערך ריק []).

עבור כל פריט, ספק מידע מדויק ועדכני. אם אינך בטוח בתאריך מדויק — ציין שנה בלבד.

פלט JSON בלבד, ללא שום טקסט לפני או אחרי:
[
  {{
    "lawType": "תיקון חוק",
    "lawName": "שם החוק המלא כולל שנה",
    "amendmentNumber": "תיקון מס' XX (אם רלוונטי)",
    "effectiveDate": "תאריך כניסה לתוקף או שנה משוערת",
    "title": "כותרת קליטה לאזרח — מה זה אומר עליו (עד 70 תווים)",
    "summary": "תקציר בשני משפטים קצרים",
    "body": "## מה השתנה?\\nהסבר מפורט של השינוי (6-8 משפטים)\\n\\n## מה המשמעות עבורך?\\nהשפעה מעשית על בעלי נכסים / רוכשים / שוכרים (6-8 משפטים)\\n\\n## מה כדאי לדעת?\\nטיפים ואזהרות (4-5 משפטים)",
    "keywords": ["מקרקעין", "רכישה"]
  }}
]"""

def parse_claude_response(raw: str) -> list:
    raw = raw.strip()
    # הסרת markdown wrappers
    raw = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # ניסיון לחלץ מערך JSON
        import re
        match = re.search(r'\[[\s\S]*\]', raw)
        if match:
            return json.loads(match.group(0))
        return []

def load_existing() -> list:
    if OUTPUT_FILE.exists():
        try:
            return json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def save_pending(items: list):
    existing = load_existing()
    # הוסף רק פריטים חדשים (לפי כותרת + שם חוק)
    existing_keys = {(e.get("lawName",""), e.get("title","")) for e in existing}
    new_items = []
    for item in items:
        key = (item.get("lawName",""), item.get("title",""))
        if key not in existing_keys:
            item["id"]        = f"leg_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{len(new_items)}"
            item["status"]    = "pending"
            item["createdAt"] = datetime.datetime.now().isoformat()
            new_items.append(item)
            existing_keys.add(key)
    all_items = existing + new_items
    OUTPUT_FILE.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_items

def send_email(new_items: list, cfg: dict):
    if not cfg["smtp_user"] or not cfg["smtp_pass"]:
        print("⚠️  SMTP credentials not configured — skipping email")
        return
    if not new_items:
        print("ℹ️  No new items — no email sent")
        return

    subject = f"⚖️ {len(new_items)} עדכוני חקיקה ממתינים לאישורך — משרד מזור"

    # HTML Body
    items_html = ""
    for i, l in enumerate(new_items, 1):
        items_html += f"""
        <div style="border:1px solid #e2e0da;border-radius:8px;padding:16px;margin-bottom:12px;background:#fafaf8">
          <span style="background:rgba(201,168,76,.15);color:#7a5a10;font-size:12px;padding:2px 8px;border-radius:4px;font-weight:600">{l.get('lawType','')}</span>
          <h3 style="color:#1B2A4A;margin:8px 0 4px;font-size:15px">{l.get('title','')}</h3>
          <p style="color:#5a6478;font-size:13px;margin:0 0 6px">{l.get('lawName','')} {l.get('effectiveDate','')}</p>
          <p style="color:#3a3a4e;font-size:13px;margin:0">{l.get('summary','')}</p>
        </div>"""

    html = f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;direction:rtl;max-width:600px;margin:0 auto;padding:20px;color:#1a1a2e">
  <div style="background:#1B2A4A;padding:20px 24px;border-radius:10px 10px 0 0">
    <h1 style="color:white;margin:0;font-size:18px">⚖️ עדכוני חקיקה — משרד מזור</h1>
    <p style="color:rgba(255,255,255,.7);margin:4px 0 0;font-size:13px">{datetime.datetime.now().strftime('%d/%m/%Y')}</p>
  </div>
  <div style="background:white;border:1px solid #e2e0da;border-top:none;padding:20px 24px;border-radius:0 0 10px 10px">
    <p style="color:#5a6478;font-size:14px">נמצאו <strong style="color:#1B2A4A">{len(new_items)} עדכוני חקיקה</strong> הממתינים לאישורך לפני פרסום:</p>
    {items_html}
    <div style="text-align:center;margin-top:20px">
      <a href="{cfg['admin_url']}#legislation"
         style="background:#C9A84C;color:#1B2A4A;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:700;font-size:15px;display:inline-block">
        ✅ כנס לאישור הפרסום ←
      </a>
    </div>
    <p style="color:#8a8a99;font-size:11px;margin-top:16px;text-align:center">
      כנס לאדמין → עדכוני חקיקה → לחץ "אשר ופרסם" על כל פריט שברצונך לפרסם.
    </p>
  </div>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = cfg["smtp_user"]
    msg["To"]      = cfg["to_email"]
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
        server.starttls()
        server.login(cfg["smtp_user"], cfg["smtp_pass"])
        server.sendmail(cfg["smtp_user"], cfg["to_email"], msg.as_string())
    print(f"✅ Email sent to {cfg['to_email']}")

def main():
    parser = argparse.ArgumentParser(description="סריקת עדכוני חקיקה")
    parser.add_argument("--full",  action="store_true", help="סרוק 10 שנים אחרונות")
    parser.add_argument("--year",  type=int, help="סרוק שנה ספציפית")
    args = parser.parse_args()

    now   = datetime.datetime.now()
    year  = args.year or now.year

    if args.full:
        from_year = now.year - 10
        period    = f"2014 עד {now.year}"
        years_range = f"{from_year}-{now.year}"
    elif args.year:
        period    = f"שנת {args.year}"
        years_range = str(args.year)
    else:
        # ברירת מחדל: שבוע אחרון
        week_ago  = now - datetime.timedelta(days=7)
        period    = f"{week_ago.strftime('%d/%m/%Y')} עד {now.strftime('%d/%m/%Y')}"
        years_range = str(now.year)

    print(f"🔍 סורק חקיקה עבור: {period}")
    print(f"📋 חוקים לבדיקה: {len(LAWS)}")

    prompt = build_prompt(period, years_range)

    print("⏳ שולח לניתוח AI...")
    raw = call_claude(prompt, max_tokens=5000)

    items = parse_claude_response(raw)
    print(f"📦 נמצאו {len(items)} עדכונים")

    if not items:
        print("ℹ️  לא נמצאו עדכוני חקיקה לתקופה זו")
        return

    new_items = save_pending(items)
    print(f"💾 נשמרו {len(new_items)} פריטים חדשים (מתוך {len(items)})")
    print(f"📄 קובץ: {OUTPUT_FILE}")

    if new_items:
        cfg = get_email_config()
        try:
            send_email(new_items, cfg)
        except Exception as e:
            print(f"⚠️  Email failed: {e}")
            print("   (הפריטים נשמרו ב-pending_legislation.json)")

    print("✅ סריקה הושלמה")

if __name__ == "__main__":
    main()

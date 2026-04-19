#!/usr/bin/env python3
"""
סריקת עדכוני חקיקה — משרד עו"ד גיל מזור
"""
import os, sys, json, datetime, argparse, re, urllib.request, urllib.parse
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent.parent / "pending_legislation.json"

LAWS = [
    'חוק המקרקעין, תשכ"ט-1969',
    'חוק המכר (דירות), תשל"ג-1973',
    'חוק בתי משותפים (חלק ו\' לחוק המקרקעין)',
    'חוק הגנת הדייר, תשל"ב-1972',
    'חוק שכירות ושאילה, תשל"א-1971',
    'חוק פינוי ובינוי, תשס"ו-2006',
    'חוק מס שבח מקרקעין, תשכ"ג-1963',
    'חוק חוזים (חלק כללי), תשל"ג-1973',
]

def call_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["CLAUDE_API_KEY"])
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

def build_prompt(period: str) -> str:
    laws = "\n".join(f"- {l}" for l in LAWS)
    return f"""אתה עוזר משפטי ישראלי בכיר לעורך דין המתמחה במקרקעין וחוזים.

סרוק שינויי חקיקה רלוונטיים מהתקופה: {period}

חוקים לסריקה (בלבד):
{laws}

כתוב עד 5 שינויים משמעותיים ביותר.
עבור כל שינוי ספק מידע מדויק ומפורט:

<ITEM>
<TYPE>סוג (תיקון חוק / חוק חדש / תקנות / צו)</TYPE>
<LAW>שם החוק המלא כולל שנת החקיקה המקורית</LAW>
<AMENDMENT>מספר התיקון וסוגו, לדוגמה: תיקון מס' 7, ס"ח XXXX</AMENDMENT>
<DATE>תאריך פרסום ברשומות ותאריך כניסה לתוקף</DATE>
<LINK>קישור לרשומות הרשמיות (nevo.co.il או fs.knesset.gov.il) — אם ידוע</LINK>
<SECTION>מספר הסעיף/ים שהשתנו או נוספו, לדוגמה: סעיף 6א, סעיף 11(ב)</SECTION>
<TITLE>כותרת קליטה לאזרח — מה זה אומר עליו (עד 65 תווים)</TITLE>
<SUMMARY>תקציר בשני משפטים</SUMMARY>
<BODY>
## המצב הקודם (לפני התיקון)
תאר את המצב המשפטי שהיה קיים לפני השינוי — מה היה הדין, מה היו הזכויות/חובות. 4-5 משפטים.

## מה השתנה
ציין את מספר הסעיף המדויק שתוקן/נוסף.
ציטוט מדויק (או קרוב ככל האפשר) של נוסח הסעיף החדש/המתוקן.
הסבר מה בדיוק השתנה — האם נוסף סעיף חדש, הוחלפה הוראה, בוטלה הגבלה וכו'. 4-5 משפטים.

## המשמעות המעשית
ניתוח השוואתי: מה הדין היה לפני ← מה הדין עכשיו.
מה ההשלכות על בעלי נכסים / רוכשי דירות / שוכרים / בתים משותפים. 5-6 משפטים.

## מה כדאי לדעת
אזהרות, מקרים שדורשים תשומת לב, המלצות פרקטיות. 3-4 משפטים.
</BODY>
</ITEM>

ללא טקסט נוסף לפני או אחרי."""

def parse_response(raw: str) -> list:
    def tag(text, t):
        m = re.search(f'<{t}>(.*?)</{t}>', text, re.DOTALL)
        return m.group(1).strip() if m else ""
    items = []
    for block in re.findall(r'<ITEM>(.*?)</ITEM>', raw, re.DOTALL):
        item = {
            "lawType":       tag(block, "TYPE"),
            "lawName":       tag(block, "LAW"),
            "amendment":     tag(block, "AMENDMENT"),
            "effectiveDate": tag(block, "DATE"),
            "link":          tag(block, "LINK"),
            "section":       tag(block, "SECTION"),
            "title":         tag(block, "TITLE"),
            "summary":       tag(block, "SUMMARY"),
            "body":          tag(block, "BODY"),
        }
        if item["title"] or item["lawName"]:
            items.append(item)
    return items

def load_existing() -> list:
    try:
        return json.loads(OUTPUT_FILE.read_text(encoding="utf-8")) if OUTPUT_FILE.exists() else []
    except:
        return []

def save_pending(items: list) -> list:
    existing = load_existing()
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
    OUTPUT_FILE.write_text(json.dumps(existing + new_items, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_items

def send_notification(items: list):
    fid = os.environ.get("FORMSPREE_ID","")
    if not fid or fid == "xyzabcde" or not items:
        print("⚠️  דילוג על שליחת מייל (Formspree לא מוגדר)")
        return
    admin_url = os.environ.get("ADMIN_URL","https://678.co.il/admin.html")
    lines = [f"עדכוני חקיקה — {datetime.datetime.now().strftime('%d/%m/%Y')}", ""]
    for i,l in enumerate(items,1):
        lines.append(f"{i}. {l.get('lawType','')} | {l.get('lawName','')}")
        lines.append(f"   {l.get('title','')}")
        lines.append(f"   {l.get('summary','')}")
        lines.append("")
    lines.append(f"לאישור: {admin_url}#legislation")
    data = urllib.parse.urlencode({
        "_subject": f"עדכוני חקיקה: {len(items)} פריטים ממתינים",
        "message":  "\n".join(lines),
        "source":   "GitHub Actions",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            f"https://formspree.io/f/{fid}", data=data,
            headers={"Content-Type":"application/x-www-form-urlencoded","Accept":"application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            print("✅ מייל נשלח" if result.get("ok") else f"⚠️ Formspree: {result}")
    except Exception as e:
        print(f"⚠️ שגיאת מייל: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="סרוק 3 שנים אחרונות")
    args = parser.parse_args()

    now = datetime.datetime.now()
    if args.full:
        period = f"{now.year - 3} עד {now.year}"
    else:
        week_ago = now - datetime.timedelta(days=7)
        period   = f"{week_ago.strftime('%d/%m/%Y')} עד {now.strftime('%d/%m/%Y')}"

    print(f"🔍 סורק: {period}")
    prompt = build_prompt(period)
    print("⏳ שולח לניתוח AI...")
    raw   = call_claude(prompt)
    items = parse_response(raw)
    print(f"📦 נמצאו {len(items)} עדכונים")
    if not items:
        print("ℹ️  לא נמצאו עדכונים")
        return
    new_items = save_pending(items)
    print(f"💾 נשמרו {len(new_items)} פריטים חדשים")
    if new_items:
        send_notification(new_items)
    print("✅ הושלם")

if __name__ == "__main__":
    main()

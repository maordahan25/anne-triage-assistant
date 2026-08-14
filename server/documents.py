"""
שכבת המסמכים של אזור המנהל — פרסור והכנה לתצוגה *בתוך* הממשק.

עיקרון מרכזי: **אין עותקים מוטמעים.** כל מסמך נקרא מהמקור החי שלו בכל
בקשה — `docs/`, `data/`, `illustrations/illustrations.json`, `README.md`,
`llm_requirements.txt` — כך שמה שמוצג הוא תמיד הגרסה שעל הדיסק. אין כאן
מטמון, אין תמונת מצב, ואין קובץ תצוגה נפרד שיכול להתיישן.

ארכיטקטורה: **מציג אחד + רנדררים לפי סוג** ולא שמונה הטמעות נפרדות.
`DOCUMENTS` הוא רשימה סגורה של מסמכים, לכל אחד `kind` אחד משמונה:

    html       — קובץ HTML שלם שמוצג ב-iframe (מצגת, לוח התקדמות)
    markdown   — Markdown שמומר ל-HTML ממותג ומוצג ב-iframe (README, CLAUDE)
    text       — טקסט גולמי בתצוגה חד-רווחית (רנדרר כללי)
    requirements — הצהרת התלויות מפורסרת לכרטיסי חבילה לפי ייעוד
    checklist  — docs/test_plan.md מפורסר לצ'קליסט של 19 נקודות עם סטטוס
    sources    — מאגר הידע החי מ-data/, מקובץ לפי תחום
    gallery    — קטלוג האיורים החי מ-illustrations/illustrations.json
    scenarios  — תרחישי ההדגמה מ-docs/demo_scenarios.json (תצוגה + הרצה)
    licenses   — רישיונות החבילות המותקנות, מסווגים, + זכויות התוכן

הצד השני (web/admin.js) מחזיק רגיסטר רנדררים באותם מפתחות בדיוק, כך
שהוספת סוג חדש היא ערך אחד כאן + רנדרר אחד שם.

למה iframe דווקא ל-html/markdown: כך ה-HTML של המסמך לעולם אינו מוזרק
ל-DOM של אזור המנהל (admin.js שומר על הכלל "טקסט רק דרך textContent"),
והמסמך מקבל את הסגנון הממותג שלו בלי להתנגש בעיצוב העמוד.

המודול הזה הוא stdlib + markdown בלבד — אין בו שום ייבוא של crew/rag/ml,
ולכן בדיקות האופליין מריצות אותו ישירות, בלי שרת ובלי מפתח API.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# הקרדיט האישי — מקור אמת אחד לכל משטחי הפרויקט (ראה credit.py).
import sys as _sys

if str(PROJECT_ROOT) not in _sys.path:
    _sys.path.insert(0, str(PROJECT_ROOT))
from credit import credit_html  # noqa: E402
DOCS_DIR = PROJECT_ROOT / "docs"
DATA_DIR = PROJECT_ROOT / "data"
ILLUSTRATIONS_DIR = PROJECT_ROOT / "illustrations"
ILLUSTRATIONS_JSON = ILLUSTRATIONS_DIR / "illustrations.json"

DEMO_SCENARIOS_JSON = DOCS_DIR / "demo_scenarios.json"

# סוגי המציגים — מקור האמת המשותף לשרת וללקוח.
KINDS = ("html", "markdown", "text", "requirements", "checklist", "sources",
         "gallery", "scenarios", "licenses")


class UnknownDocument(KeyError):
    """מפתח שאינו ברשימה הסגורה — 404, לא שגיאת שרת."""


@dataclass(frozen=True)
class DocSpec:
    """
    מסמך אחד ברשימה הסגורה.

    source   — מה שהמציג קורא בפועל (קובץ או תיקייה). זהו "המקור החי".
    download — קובץ להורדה כגיבוי; לרוב זהה ל-source, ולעיתים קובץ אחר
               (למשל הסטוריבורד: המציג בונה גלריה מה-JSON החי, וההורדה
               נשארת קובץ ה-xlsx המקורי).
    page_lang/page_dir — שפת המסמך *עצמו* וכיוון הכתיבה שלו בעמוד הממותג.
               ברירת המחדל עברית/rtl, כי כך כתובים כל מסמכי הפרויקט. מסמך
               באנגלית חייב en/ltr: ב-rtl הפיסוק בסוף שורה נופל בצד הלא
               נכון, וקורא מסך מכריז טקסט אנגלי בהגייה עברית (WCAG 3.1.1,
               שפת העמוד — בניגוד ל-3.1.2 שאינו חל לפי ת"י 5568).
               ההודעות של "קובץ חסר/ריק" נשארות עברית תמיד — הן הודעות
               הממשק, לא תוכן המסמך.
    """

    key: str
    title: str
    description: str
    kind: str
    source: Path
    download: Path | None = None
    download_media_type: str | None = None
    download_inline: bool = False
    live_note_he: str = ""
    page_lang: str = "he"
    page_dir: str = "rtl"

    @property
    def download_path(self) -> Path | None:
        return self.download if self.download is not None else (
            self.source if self.source.is_file() else None
        )


# ── הרשימה הסגורה ────────────────────────────────────────────────────────
# רשימה סגורה = אין מעבר על נתיבים (path traversal): המפתח שמגיע מהדפדפן
# הוא תמיד מפתח במילון הזה, לעולם לא נתיב. אין כאן .env ואין קובצי לוג.
DOCUMENTS: dict[str, DocSpec] = {
    "presentation": DocSpec(
        key="presentation",
        title="מצגת הפרויקט",
        description="המצגת המלאה — ארכיטקטורה, סוכנים ובקרת איכות",
        kind="html",
        # המצגת היא היום קובץ HTML (הקובץ הישן anne_presentation.pptx כבר
        # אינו קיים) — ולכן היא מוצגת בתוך הממשק ולא יורדת כקובץ.
        source=DOCS_DIR / "anne_presentation.html",
        download_media_type="text/html; charset=utf-8",
        download_inline=True,
        live_note_he="נטענת מהמקור החי בכל פתיחה — תמיד הגרסה העדכנית.",
    ),
    "specification": DocSpec(
        key="specification",
        title="מסמך איפיון",
        description="הגדרת המערכת — מטרות, סקופ, דרישות, ארכיטקטורה "
                    "וגבולות בטיחות",
        kind="markdown",
        source=DOCS_DIR / "specification.md",
        download_media_type="text/plain; charset=utf-8",
        download_inline=True,
        live_note_he="נקרא מהמסמך החי — עריכה בו משנה מיד את מה שמוצג כאן.",
    ),
    "progress": DocSpec(
        key="progress",
        title="לוח התקדמות",
        description="לוח ההתקדמות של הפרויקט — שלבים ומצב ביצוע",
        kind="html",
        source=DOCS_DIR / "anne_progress_dashboard.html",
        download_media_type="text/html; charset=utf-8",
        download_inline=True,
        live_note_he="נטען מהמקור החי בכל פתיחה.",
    ),
    "test_plan": DocSpec(
        key="test_plan",
        title="תוכנית הבדיקות",
        description="19 נקודות הבדיקה — הבסיס לסיכום של סוויטת הבדיקות",
        kind="checklist",
        source=DOCS_DIR / "test_plan.md",
        download_media_type="text/plain; charset=utf-8",
        download_inline=True,
        live_note_he="הצ'קליסט נבנה מהמסמך החי בכל טעינה.",
    ),
    "sources": DocSpec(
        key="sources",
        title="מקורות הידע",
        description="מאגר הידע של אן — כל מסמכי הידע לפי תחום, עם המקור שלהם",
        kind="sources",
        # המקור החי הוא תיקיית data/ עצמה, לא מסמך מסכם: כך מסמך שנוסף
        # למאגר מופיע כאן מיד, בלי לעדכן שום רשימה.
        source=DATA_DIR,
        download=DOCS_DIR / "SOURCES.docx",
        live_note_he="נקרא ישירות ממאגר הידע — כולל כל מסמך שנוסף אליו.",
    ),
    "storyboard": DocSpec(
        key="storyboard",
        title="סטוריבורד האיורים",
        description="20 האיורים המודרכים — שם, קטגוריה ושלבי ההדגמה",
        kind="gallery",
        source=ILLUSTRATIONS_JSON,
        download=DOCS_DIR / "illustrations_storyboard.xlsx",
        live_note_he="הגלריה נבנית מקטלוג האיורים החי.",
    ),
    "readme": DocSpec(
        key="readme",
        title="מדריך הפרויקט",
        description="התיעוד המלא — התקנה, הרצה, ארכיטקטורה ובדיקות",
        kind="markdown",
        source=PROJECT_ROOT / "README.md",
        download_media_type="text/plain; charset=utf-8",
        download_inline=True,
    ),
    "readme_en": DocSpec(
        key="readme_en",
        title="מדריך הפרויקט באנגלית",
        description="אותו תיעוד מלא בתרגום לאנגלית — התקנה, הרצה, "
                    "ארכיטקטורה ובדיקות",
        kind="markdown",
        source=PROJECT_ROOT / "README.en.md",
        download_media_type="text/plain; charset=utf-8",
        download_inline=True,
        # המסמך היחיד בפרויקט שאינו עברית, ולכן העמוד הממותג שלו הוא
        # en/ltr ולא ברירת המחדל he/rtl.
        page_lang="en",
        page_dir="ltr",
    ),
    "architecture": DocSpec(
        key="architecture",
        title="מדריך הארכיטקטורה",
        description="הנחיות העבודה בקוד — שכבות, החלטות תכנון והנימוקים",
        kind="markdown",
        source=PROJECT_ROOT / "CLAUDE.md",
        download_media_type="text/plain; charset=utf-8",
        download_inline=True,
    ),
    "requirements": DocSpec(
        key="requirements",
        title="דרישות המערכת",
        description="כל החבילות שהפרויקט צריך, מקובצות לפי ייעוד — עם "
                    "הרציונל לכל קיבוע גרסה",
        kind="requirements",
        source=PROJECT_ROOT / "llm_requirements.txt",
        download_media_type="text/plain; charset=utf-8",
        download_inline=True,
        live_note_he="נבנה מהצהרת התלויות החיה, והגרסאות המותקנות נקראות "
                     "מהסביבה שמריצה את השרת.",
    ),
    "accessibility": DocSpec(
        key="accessibility",
        title="הצהרת נגישות",
        description="היעד (WCAG 2.1 AA), מה מיושם, מה נבדק ומה חסר — "
                    "הצהרת שאיפה ולא הצהרת עמידה משפטית",
        kind="markdown",
        # אותו קובץ מוגש גם בנתיב הציבורי /accessibility (בלי טוקן):
        # הצהרת נגישות שרק מנהל יכול לקרוא אינה שווה דבר.
        source=DOCS_DIR / "accessibility.md",
        download_media_type="text/plain; charset=utf-8",
        download_inline=True,
        live_note_he="נקראת מאותו מסמך חי שמוצג למשתמשים בהצהרת "
                     "הנגישות הציבורית.",
    ),
    "licenses": DocSpec(
        key="licenses",
        title="רישיונות וזכויות",
        description="רישיון כל חבילה מותקנת, מסווג לפי רמת החופש — "
                    "ומצב הזכויות של התוכן והאיורים",
        kind="licenses",
        # המקור להורדה/להצגה הוא הצהרת התלויות; הרישיונות עצמם נסרקים
        # מהחבילות המותקנות בסביבה בזמן הבקשה (ראה load_license_report).
        source=PROJECT_ROOT / "llm_requirements.txt",
        download_media_type="text/plain; charset=utf-8",
        download_inline=True,
        live_note_he="הרישיונות נסרקים מהחבילות המותקנות בסביבה בכל פתיחה "
                     "— אין רשימה שמורה שיכולה להתיישן.",
    ),
    "demo_scenarios": DocSpec(
        key="demo_scenarios",
        title="תרחישי הדגמה",
        description="תרחישי השיחה להדגמה חיה מול אן — עם הרצה אוטומטית",
        kind="scenarios",
        # מקור האמת היחיד לתרחישים. אותו קובץ מזין גם את מקטע התרחישים
        # בלוח המנהל וגם את המריץ בצ'אט — אין עותק שני בקוד.
        source=DEMO_SCENARIOS_JSON,
        download_media_type="application/json; charset=utf-8",
        download_inline=True,
        live_note_he="נבנים מקובץ התרחישים החי — עריכה בו משנה גם את "
                     "כרטיסי התרחישים וגם את מה שהמריץ שולח בפועל.",
    ),
}


def get_spec(key: str) -> DocSpec:
    """המפרט של מסמך מהרשימה הסגורה; מפתח לא מוכר -> UnknownDocument."""
    spec = DOCUMENTS.get(key)
    if spec is None:
        raise UnknownDocument(key)
    return spec


# ── עזרי קבצים ───────────────────────────────────────────────────────────
def _read_text(path: Path) -> str | None:
    """קריאת קובץ טקסט; קובץ חסר/לא קריא -> None (ולא חריגה)."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def size_he(path: Path) -> str:
    """גודל קובץ בפורמט קריא (KB/MB) — להצגה בכרטיס."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


def _source_exists(spec: DocSpec) -> bool:
    return spec.source.exists()


# ── רנדרר: צ'קליסט תוכנית הבדיקות ────────────────────────────────────────
# הסטטוס מסומן במסמך באמוג'י בסוף כותרת הנקודה. המיפוי הזה הוא גם
# מקור הצבע בתצוגה (class), וגם מקור הספירה בסרגל ההתקדמות.
STATUS_BY_EMOJI = {
    "✅": ("active", "פעיל"),
    "🟡": ("partial", "חלקי"),
    "⏳": ("skipped", "מדולג"),
}
_NUMBERED_HEADING = re.compile(r"^##\s*(\d+)\.\s*(.+?)\s*$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
# "- **מדולג (skip):** <סיבה>" — הסיבה היא כל מה שאחרי הנקודתיים.
_SKIP_BULLET = re.compile(r"^\*\*\s*מדולג\s*\(skip\)\s*:?\*\*\s*:?\s*(.*)$")
_ACTIVE_BULLET = re.compile(r"^\*\*\s*פעיל עכשיו\s*:?\*\*\s*:?\s*(.*)$")


def _strip_markdown_emphasis(text: str) -> str:
    """הסרת סימוני הדגשה/קוד — התצוגה היא כרטיס מעוצב, לא markdown."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()


def parse_test_plan(text: str) -> dict:
    """
    פרסור docs/test_plan.md לצ'קליסט מובנה.

    מוחזר: פריט לכל נקודה ממוספרת (מספר, כותרת, סטטוס, תבליטים, סיבת
    דילוג אם יש) + סיכום לסרגל ההתקדמות. מסמך ריק/בלי נקודות ממוספרות
    מחזיר רשימה ריקה וסיכום מאופס — לא חריגה.
    """
    items: list[dict] = []
    current: dict | None = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        heading = _NUMBERED_HEADING.match(line)
        if heading:
            number, title = int(heading.group(1)), heading.group(2)
            status_key, status_he = "active", "פעיל"
            for emoji, (key, label) in STATUS_BY_EMOJI.items():
                if emoji in title:
                    status_key, status_he = key, label
                    title = title.replace(emoji, "")
                    break
            current = {
                "number": number,
                "title": _strip_markdown_emphasis(title),
                "status": status_key,
                "status_he": status_he,
                "bullets": [],
                "skip_reason": "",
                "active_note": "",
            }
            items.append(current)
            continue
        if line.startswith("## ") or line.startswith("# "):
            current = None  # מקטע לא-ממוספר (מקרא / דרישות פלט)
            continue
        if current is None:
            continue
        bullet = _BULLET.match(line)
        if not bullet:
            continue
        body = bullet.group(1).strip()
        skip = _SKIP_BULLET.match(body)
        active = _ACTIVE_BULLET.match(body)
        if skip:
            current["skip_reason"] = _strip_markdown_emphasis(skip.group(1))
        elif active:
            current["active_note"] = _strip_markdown_emphasis(active.group(1))
        else:
            current["bullets"].append(_strip_markdown_emphasis(body))

    summary = {
        "total": len(items),
        "active": sum(1 for item in items if item["status"] == "active"),
        "partial": sum(1 for item in items if item["status"] == "partial"),
        "skipped": sum(1 for item in items if item["status"] == "skipped"),
    }
    return {
        "items": items,
        "summary": summary,
        "legend": [
            {"status": "active", "label": "פעיל", "meaning": "הרכיב קיים ונבדק בפועל"},
            {"status": "partial", "label": "חלקי",
             "meaning": "חלק מהרכיב קיים; השאר מסומן כדילוג עם סיבה"},
            {"status": "skipped", "label": "מדולג",
             "meaning": "הרכיב טרם נבנה — שלד בדיקה עם סיבה מוצהרת"},
        ],
    }


# ── רנדרר: מאגר הידע החי (data/) ─────────────────────────────────────────
TOPIC_HE = {
    "wounds": "פצעים וחתכים",
    "anxiety": "חרדה",
    "dehydration": "התייבשות",
    "cold": "הצטננות",
}
# ארבעת המקטעים הקבועים בכל מסמך ידע — הסדר כאן הוא סדר התצוגה.
SECTION_ORDER = ("תסמינים", "טיפול ראשוני", "המשך טיפול", "פנייה מיידית")


def classify_source_type(raw: str) -> tuple[str, str]:
    """
    סיווג שורת "סוג מקור:" לשלוש קבוצות תג בצבע שונה.

    הניסוח במסמכים חופשי — "רפואי רשמי (קופת חולים)", "מסחרי (אתר מותג)
    — מבוסס מידע רפואי", "מדריך כללי (לא מקור רפואי רשמי)" — ולכן הסיווג
    נעשה על **התווית הראשית בלבד**: מה שלפני הסוגר או המקף.

    זו לא קפדנות לשמה אלא באג מאומת: חיפוש תת-מחרוזת על כל השורה סיווג
    13 מדריכים כלליים כ"רפואי רשמי", כי ההסתייגות שבסוגריים ("לא מקור
    רפואי רשמי") מכילה בדיוק את אותן מילים. ברירת המחדל היא "מדריך כללי"
    — הקבוצה הזהירה מבין השלוש.
    """
    text = (raw or "").strip()
    # התווית הראשית: עד הסוגר הראשון או המקף המפריד.
    primary = re.split(r"[(—–-]", text, maxsplit=1)[0].strip()
    if "רפואי רשמי" in primary:
        return "official", "רפואי רשמי"
    if "מסחרי" in primary:
        return "commercial", "מסחרי"
    return "guide", "מדריך כללי"


def parse_knowledge_document(path: Path) -> dict | None:
    """
    פרסור מסמך ידע בודד מ-data/ למבנה תצוגה.

    מבנה הקובץ: כותרת `# `, שורות מטא (`**קטגוריה:**`/`**topic:**`),
    ארבעה מקטעי `## `, ואז `---` ותחתית עם `מקור:` / `סוג מקור:` /
    `הערה:`. קובץ חסר או לא קריא -> None; קובץ קיים אך חלקי מוחזר עם
    השדות שכן נמצאו (התצוגה לא נשענת על אף שדה בודד).
    """
    text = _read_text(path)
    if text is None:
        return None

    # הפרדת התחתית (אחרי קו ה---- האחרון) מגוף המסמך.
    body, footer = text, ""
    marker = "\n---"
    if marker in text:
        head, _, tail = text.rpartition(marker)
        body, footer = head, tail

    title, category, sections = "", "", []
    current: dict | None = None
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            current = {"heading": line[3:].strip(), "bullets": []}
            sections.append(current)
            continue
        stripped = line.strip()
        if stripped.startswith("**קטגוריה:**"):
            category = stripped.split("**קטגוריה:**", 1)[1].strip()
            continue
        if not stripped or current is None:
            continue
        bullet = _BULLET.match(stripped)
        if bullet:
            current["bullets"].append(_strip_markdown_emphasis(bullet.group(1)))
        else:
            current["bullets"].append(_strip_markdown_emphasis(stripped))

    source_name, source_url, source_type_raw, note = "", "", "", ""
    for raw_line in footer.splitlines():
        line = raw_line.strip()
        if line.startswith("מקור:"):
            value = line.split("מקור:", 1)[1].strip()
            # "שם המקור — כותרת — https://..." : ה-URL הוא האסימון האחרון
            match = re.search(r"(https?://\S+)", value)
            if match:
                source_url = match.group(1)
                value = value[: match.start()].strip(" —-–")
            source_name = value
        elif line.startswith("סוג מקור:"):
            source_type_raw = line.split("סוג מקור:", 1)[1].strip()
        elif line.startswith("הערה:"):
            note = line.split("הערה:", 1)[1].strip()

    type_key, type_he = classify_source_type(source_type_raw)
    return {
        "file": path.name,
        "title": title or path.stem,
        "category": category,
        "source_name": source_name,
        "source_url": source_url,
        "source_type": type_key,
        "source_type_he": type_he,
        "source_type_raw": source_type_raw,
        "note": note,
        "sections": sections,
    }


def load_knowledge_sources(data_dir: Path | None = None) -> dict:
    """
    כל מאגר הידע החי, מקובץ לפי תחום (תת-תיקייה של data/).

    תיקייה חסרה או ריקה מוחזרת כרשימת תחומים ריקה — התצוגה מציגה הודעה
    מסודרת ולא נשברת.
    """
    root = data_dir if data_dir is not None else DATA_DIR
    topics: list[dict] = []
    totals = {"documents": 0, "official": 0, "commercial": 0, "guide": 0}
    if not root.is_dir():
        return {"topics": topics, "totals": totals, "available": False}

    for topic_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        documents = []
        for md_path in sorted(topic_dir.glob("*.md")):
            document = parse_knowledge_document(md_path)
            if document is None:
                continue
            documents.append(document)
            totals["documents"] += 1
            totals[document["source_type"]] += 1
        if not documents:
            continue
        topics.append({
            "topic": topic_dir.name,
            "title_he": TOPIC_HE.get(
                topic_dir.name, documents[0].get("category") or topic_dir.name
            ),
            "documents": documents,
        })
    return {"topics": topics, "totals": totals, "available": True}


# ── רנדרר: גלריית האיורים החיה ───────────────────────────────────────────
def load_illustration_gallery(catalog_path: Path | None = None) -> dict:
    """
    גלריית האיורים מהרשימה הסגורה, מקובצת לפי קטגוריה.

    JSON חסר/פגום -> גלריה ריקה עם הודעה בעברית (available=False), לא
    חריגה: קטלוג שבור לא אמור להפיל את אזור המנהל. לכל פריט מסומן אם
    קובץ התמונה עצמו קיים על הדיסק, כדי שהתצוגה תוכל להראות מסגרת
    חלופית במקום תמונה שבורה.
    """
    path = catalog_path if catalog_path is not None else ILLUSTRATIONS_JSON
    raw = _read_text(path)
    if raw is None:
        return {"categories": [], "total": 0, "available": False,
                "message_he": "קטלוג האיורים אינו קיים במקומו."}
    try:
        catalog = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"categories": [], "total": 0, "available": False,
                "message_he": f"קטלוג האיורים אינו JSON תקין (שורה {exc.lineno})."}

    entries = catalog.get("illustrations")
    if not isinstance(entries, dict) or not entries:
        return {"categories": [], "total": 0, "available": False,
                "message_he": "קטלוג האיורים ריק — אין מה להציג."}

    images_dir = path.parent
    grouped: dict[str, list[dict]] = {}
    total = 0
    for key, record in entries.items():
        if not isinstance(record, dict):
            continue
        file_name = str(record.get("file") or "")
        steps = [str(step) for step in (record.get("steps") or [])]
        category = str(record.get("category") or "כללי")
        grouped.setdefault(category, []).append({
            "id": key,
            "name": str(record.get("name") or key),
            "file": file_name,
            "image_url": f"/illustrations/{file_name}" if file_name else "",
            "image_exists": bool(file_name and (images_dir / file_name).exists()),
            "steps": steps,
        })
        total += 1

    categories = [
        {"name": name, "items": sorted(items, key=lambda item: item["name"])}
        for name, items in sorted(grouped.items())
    ]
    return {"categories": categories, "total": total, "available": True,
            "message_he": ""}


# ── רנדרר: תרחישי ההדגמה (docs/demo_scenarios.json) ──────────────────────
# תמונות ההדגמה מוגשות מ-/assets (StaticFiles), ולכן זו גם התיקייה
# היחידה שממנה מותר לשלב attach_image לקחת קובץ.
DEMO_IMAGE_ROOT = "assets"
DEMO_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _demo_image_url(raw_path) -> str | None:
    """
    נתיב תמונת הדגמה מהקובץ -> URL להגשה, או None אם אינו תקין.

    הכלל צר בכוונה: נתיב יחסי בלבד, מתחת ל-assets/, בסיומת תמונה
    נתמכת, וקובץ שקיים בפועל. אין כאן "בערך" — שלב שמצביע על קובץ
    שאינו קיים היה נראה תקין ברשימת התרחישים ומתפוצץ מול קהל.
    """
    text = str(raw_path or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or ".." in text.split("/"):
        return None
    if not text.startswith(f"{DEMO_IMAGE_ROOT}/"):
        return None
    if not text.lower().endswith(DEMO_IMAGE_SUFFIXES):
        return None
    target = (PROJECT_ROOT / text).resolve()
    root = (PROJECT_ROOT / DEMO_IMAGE_ROOT).resolve()
    if not target.is_file() or root not in target.parents:
        return None
    return f"/{text}"


def _parse_scenario_steps(raw_messages) -> tuple[list[dict], list[str]]:
    """
    רשימת ה-messages של תרחיש -> (steps, messages).

    כל פריט הוא אחד משלושה:
      * מחרוזת — הודעת משתמש רגילה.
      * {"type": "await_image", ...} — המריץ עוצר, מבקש מהמשתמש לצרף
        תמונה, וממשיך מיד כשהיא צורפה (הדגמה עם תמונה של המשתמש).
      * {"type": "attach_image", "image_path": ...} — המריץ מצרף
        אוטומטית תמונת הדגמה קבועה מהריפו וממשיך; ההרצה עוברת מקצה
        לקצה בלי התערבות. שני הסוגים נתמכים ומשמשים זה לצד זה.
    בשניהם ההודעה שנשלחת עם התמונה היא message_he.

    למה שני מבנים ולא אחד: `messages` הוא חוזה קיים (המציג באזור המנהל
    ובדיקות הסוללה קוראים אותו), ולכן הוא נשאר *רשימת ההודעות בלבד*;
    `steps` הוא הרצף המלא שהמריץ מבצע. שניהם נגזרים מאותה רשימה בקובץ
    — אין שני מקורות אמת.

    נתיב התמונה נבדק כאן ולא בדפדפן: הוא חייב להיות יחסי, מתחת ל-assets/
    ולהצביע על קובץ קיים. הקובץ מגיע מהריפו ולא מהמשתמש, ולכן זו הגנת
    עומק — אבל היא זולה, והיא גם מה שמונע שלב "שבור בשקט" בהדגמה חיה:
    נתיב פסול מוריד את השלב להודעה רגילה, והתרחיש עדיין רץ.
    """
    steps: list[dict] = []
    messages: list[str] = []
    for item in raw_messages or []:
        if isinstance(item, dict):
            kind = str(item.get("type") or "").strip()
            text = str(item.get("message_he") or "").strip()
            if not text or kind not in {"await_image", "attach_image"}:
                continue    # סוג שלב לא מוכר / בלי הודעה — מדולג בשקט
            step = {
                "type": kind,
                "instruction_he": str(item.get("instruction_he") or "").strip(),
                "message_he": text,
            }
            if kind == "attach_image":
                image_url = _demo_image_url(item.get("image_path"))
                if not image_url:
                    # אין תמונה תקינה — ממשיכים כהודעה רגילה במקום
                    # להשאיר שלב שייתקע בהדגמה.
                    step = {"type": "message", "message_he": text}
                else:
                    step["image_url"] = image_url
            steps.append(step)
            messages.append(text)
            continue
        text = str(item).strip()
        if not text:
            continue
        steps.append({"type": "message", "message_he": text})
        messages.append(text)
    return steps, messages


def load_demo_scenarios(catalog_path: Path | None = None) -> dict:
    """
    תרחישי ההדגמה מהמקור היחיד, מוכנים גם לתצוגה וגם להרצה.

    לכל תרחיש: מזהה, כותרת, "מה מדגים", ורשימת הודעות המשתמש לפי הסדר —
    בדיוק מה שהמריץ בצ'אט שולח, אחת-אחת, כקלט משתמש רגיל.

    קובץ חסר / JSON פגום / רשימה ריקה מוחזרים כ-available=False עם הודעה
    בעברית (ולא כחריגה): תקלה בקובץ הדגמה לא אמורה להפיל את אזור המנהל.
    תרחיש בלי מזהה או בלי הודעות מדולג בשקט — עדיף להציג את מה שתקין.
    """
    path = catalog_path if catalog_path is not None else DEMO_SCENARIOS_JSON
    raw = _read_text(path)
    if raw is None:
        return {"scenarios": [], "doctors": {}, "available": False,
                "total_turns": 0,
                "message_he": "קובץ התרחישים אינו קיים במקומו."}
    try:
        catalog = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"scenarios": [], "doctors": {}, "available": False,
                "total_turns": 0,
                "message_he": f"קובץ התרחישים אינו JSON תקין (שורה {exc.lineno})."}

    entries = catalog.get("scenarios")
    if not isinstance(entries, list) or not entries:
        return {"scenarios": [], "doctors": {}, "available": False,
                "total_turns": 0,
                "message_he": "אין תרחישים מוגדרים בקובץ."}

    doctors = catalog.get("doctors")
    scenarios: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("id") or "").strip()
        steps, messages = _parse_scenario_steps(entry.get("messages"))
        if not key or not messages:
            continue
        scenarios.append({
            "id": key,
            "title": str(entry.get("title") or key),
            "topic": str(entry.get("topic") or ""),
            "doctor": str(entry.get("doctor") or ""),
            "demonstrates": str(entry.get("demonstrates") or ""),
            "expectation_he": str(entry.get("expectation_he") or ""),
            # messages נשאר רשימת ההודעות בלבד (תאימות לאחור: המציג,
            # התצוגה באזור המנהל והבדיקות מסתמכים עליה), ו-steps נושא את
            # הרצף המלא — כולל שלבים שאינם הודעה, כמו המתנה לתמונה.
            "messages": messages,
            "steps": steps,
            "turns": len(messages),
        })
    if not scenarios:
        return {"scenarios": [], "doctors": {}, "available": False,
                "total_turns": 0,
                "message_he": "אין תרחיש תקין בקובץ (חסר מזהה או הודעות)."}
    return {
        "scenarios": scenarios,
        "doctors": doctors if isinstance(doctors, dict) else {},
        "total_turns": sum(item["turns"] for item in scenarios),
        "available": True,
        "message_he": "",
    }


# ── רנדרר: רישיונות החבילות + זכויות התוכן ───────────────────────────────
# השאלה שהתצוגה הזו עונה עליה: **האם יש בפרויקט חבילה שאינה בשימוש חופשי,
# או שיש עליה מגבלת זכויות?** לכן היא לא רק מציגה רישיונות אלא מסווגת
# אותם לארבע קטגוריות ומרימה דגל על מה שדורש בדיקה.
#
# מאיפה הנתונים: `importlib.metadata` של הספרייה הסטנדרטית, כלומר
# **החבילות שמותקנות בפועל בסביבה שמריצה את השרת** — לא רשימה שנשמרה
# בקובץ ולא פלט שהודבק. זה גם מייתר תלות חדשה: pip-licenses היה מוסיף
# חבילה (ואת prettytable) כדי לקרוא בדיוק את אותה מטא-דאטה.
# שלושה שדות אפשריים לרישיון, ולכן כולם נסרקים יחד: License-Expression
# (SPDX, הדרך המודרנית), License (טקסט חופשי) ו-Classifier של
# "License :: ...". בסביבה הזו מופיעים כל השלושה בפועל.
LICENSE_CATEGORIES: dict[str, dict] = {
    "strong_copyleft": {
        "label_he": "קופילפט חזק",
        "tone": "danger",
        "examples_he": "GPL · AGPL",
        "meaning_he": (
            "דגל אדום: רישיון שעלול לחייב שחרור הקוד שלנו בתנאים דומים "
            "בעת הפצה. דורש בדיקה משפטית לפני שימוש מסחרי או הפצה."
        ),
    },
    "unknown": {
        "label_he": "לא מזוהה / קנייני",
        "tone": "unknown",
        "examples_he": "אין מטא-דאטה · Proprietary",
        "meaning_he": (
            "לא נמצא רישיון מוכר במטא-דאטה של החבילה, או שהיא מסומנת "
            "כקניינית — לבדיקה ידנית בעמוד החבילה."
        ),
    },
    "weak_copyleft": {
        "label_he": "קופילפט חלש",
        "tone": "warn",
        "examples_he": "LGPL · MPL-2.0",
        "meaning_he": (
            "מותר לשימוש ולהפצה גם בקוד סגור, אבל שינוי בחבילה עצמה "
            "מחייב שיתוף השינוי. אנחנו צורכים אותן כמו שהן."
        ),
    },
    "permissive": {
        "label_he": "מתירני",
        "tone": "ok",
        "examples_he": "MIT · BSD · Apache-2.0 · ISC · PSF",
        "meaning_he": (
            "שימוש חופשי, כולל מסחרי, בתנאי שמירת הודעת הרישיון "
            "והקרדיט."
        ),
    },
}

# סדר התצוגה: מה שדורש תשומת לב עולה למעלה (ולא לפי אלפבית או כמות).
CATEGORY_DISPLAY_ORDER = ("strong_copyleft", "unknown", "weak_copyleft",
                          "permissive")
# סדר ההכרעה כשבחבילה אחת מופיעים כמה רישיונות (למשל
# "MPL-2.0 AND (Apache-2.0 OR MIT)"): **המחמיר גובר**.
_CATEGORY_SEVERITY = {"strong_copyleft": 3, "weak_copyleft": 2, "permissive": 1}

# GPL/AGPL אך לא LGPL: ה-lookbehind חוסם את ה-"gpl" שבתוך "lgpl".
_STRONG_RE = re.compile(
    r"(?<![a-z])(?:agpl|gpl(?![a-z])|gnu affero|gnu general public)", re.I,
)
_WEAK_RE = re.compile(
    r"(?<![a-z])(?:lgpl|mpl|mozilla public|gnu lesser|eupl|cddl|"
    r"epl(?![a-z])|eclipse public|osl(?![a-z])|sleepycat)", re.I,
)
_PERMISSIVE_RE = re.compile(
    r"(?<![a-z])(?:mit(?![a-z])|mit-cmu|bsd|apache|isc(?![a-z])|"
    r"psf(?![a-z])|python software foundation|python-2|cnri|zlib|zpl|"
    r"unlicense|cc0|wtfpl|bsl-1|boost software|postgresql|ncsa|hpnd|"
    r"public domain|afl(?![a-z])|apache software)", re.I,
)
_PROPRIETARY_RE = re.compile(
    r"proprietary|all rights reserved|commercial license|\beula\b", re.I,
)


def classify_license(raw: str) -> dict:
    """
    סיווג טקסט רישיון לאחת מארבע הקטגוריות.

    ההכרעה היא **לפי המחמיר**: חבילה עם "MPL-2.0 AND MIT" היא קופילפט
    חלש, לא מתירנית. טקסט ריק, או טקסט שאין בו שום רישיון מוכר, מסווג
    ל-"לא מזוהה / קנייני" — בכוונה: עדיף דגל לבדיקה ידנית על ניחוש.
    מחזיר {category, matched_he, needs_review}.
    """
    text = (raw or "").strip()
    if not text:
        return {"category": "unknown", "matched_he": "אין מטא-דאטה של רישיון",
                "needs_review": True}
    found: list[str] = []
    if _STRONG_RE.search(text):
        found.append("strong_copyleft")
    if _WEAK_RE.search(text):
        found.append("weak_copyleft")
    if _PERMISSIVE_RE.search(text):
        found.append("permissive")
    if not found:
        proprietary = bool(_PROPRIETARY_RE.search(text))
        return {
            "category": "unknown",
            "matched_he": "מסומן כקנייני" if proprietary else "רישיון לא מזוהה",
            "needs_review": True,
        }
    category = max(found, key=lambda key: _CATEGORY_SEVERITY[key])
    return {"category": category, "matched_he": "", "needs_review": False}


def normalize_package_name(name: str) -> str:
    """נרמול שם חבילה לפי PEP 503 — כך ששמות מ-requirements ומהמטא-דאטה יפגשו."""
    return re.sub(r"[-_.]+", "-", (name or "").strip()).lower()


# ── רנדרר: דרישות המערכת ─────────────────────────────────────────────────
# המסמך הזה הוצג קודם כטקסט גולמי במסגרת חד-רווחית: 105 שורות שרובן הערות
# עברית, ובתוכן פזורות 15 שורות התלות עצמן. הכל נכון ובלתי קריא. כאן הוא
# מפורסר למה שהוא באמת — **רשימת חבילות מקובצת לפי ייעוד** — כך שהתצוגה
# יכולה להיות כרטיס לכל חבילה עם תג גרסה, ולמעלה סיכום כמותי.
#
# הקיבוץ אינו נגזר מהקוד אלא מהמסמך עצמו: כותרות המקטעים בקובץ
# (`# ── ... ──`) *הן* חלוקת הייעוד, ולכן אין כאן מיפוי שני שיכול
# להתיישן כשמוסיפים תלות. הרציונל שכתוב מעל כל תלות נשמר במלואו — הוא
# תוכן המסמך, לא תווית ממשק.
_GROUP_HEADER_RE = re.compile(r"^#\s*[─\-]{2,}\s*(.+?)\s*[─\-]{2,}\s*$")
# פרטי גרסה: השם, extras אופציונליים, וכל מה שאחריהם (הקיבוע/הטווח).
_REQUIREMENT_LINE_RE = re.compile(r"^([A-Za-z0-9][\w.\-]*)(\[[^\]]+\])?\s*(.*)$")
# נתיב שמופיע בסוגריים בכותרת מקטע ("(dashboard/)") — מוסר מהתצוגה.
_PATH_PARENS_RE = re.compile(r"\s*\([^()]*/[^()]*\)")
# המקטע הראשון בקובץ אינו נושא כותרת (הוא נפתח בהוראות ההתקנה), ולכן יש
# לו שם ידידותי משלו.
DEFAULT_REQUIREMENT_GROUP_HE = "ליבת מאגר הידע (RAG) — הטמעות ואינדקס"
# משפט אחד לתקציר הכרטיס; הרציונל המלא נשאר מתחתיו (נפתח בלחיצה).
_SUMMARY_MAX_CHARS = 150


def _group_title_he(raw: str) -> str:
    """כותרת מקטע לתצוגה — בלי הנתיב שבסוגריים (אין נתיבים בתצוגה)."""
    cleaned = _PATH_PARENS_RE.sub("", raw or "").strip(" —–-")
    return cleaned or DEFAULT_REQUIREMENT_GROUP_HE


def _version_tag_he(spec: str) -> dict:
    """
    תג הגרסה של חבילה: מקובעת (==), טווח, או בלי דרישה.

    ההבחנה חשובה בפרויקט הזה יותר מהרגיל: הקיבועים כאן (numpy<2,
    crewai==1.6.1) הם החלטות תאימות שהרציונל שלהן כתוב במסמך, ולכן
    התצוגה מבדילה ביניהן ולא מציגה מחרוזת אחת אטומה.
    """
    text = (spec or "").strip()
    if not text:
        return {"kind": "any", "label_he": "כל גרסה", "spec": ""}
    if text.startswith("=="):
        return {"kind": "pinned", "label_he": f"מקובעת {text[2:].strip()}",
                "spec": text}
    return {"kind": "range", "label_he": text, "spec": text}


def _clip(text: str) -> str:
    """קיצוץ לתקציר כרטיס, על גבול מילה."""
    if len(text) <= _SUMMARY_MAX_CHARS:
        return text
    return text[:_SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + "…"


def _package_summary(name: str, rationale: str) -> str:
    """
    התקציר שמוצג על כרטיס החבילה.

    כשבלוק הערות אחד מכסה כמה תלויות (כך כתוב בקובץ: "fastapi — ...",
    "uvicorn — ...", "httpx — ..." ואז הערה משותפת), המשפט הראשון של
    הבלוק מדבר על החבילה הראשונה בלבד — ולכן הוא היה מוצג בשגגה גם על
    שלוש האחרות. כאן מחפשים קודם את המשפט ש*פותח בשם החבילה הזו*, ורק
    בהיעדרו נלקח המשפט הראשון של הבלוק.
    """
    plain = " ".join((rationale or "").split())
    if not plain:
        return ""
    match = re.search(
        rf"(?:^|[\s(]){re.escape(name)}\s*[—–:-]\s*(.+)", plain, re.IGNORECASE,
    )
    body = match.group(1) if match else plain
    return _clip(body.split(". ")[0].rstrip("."))


def _installed_versions() -> dict[str, str]:
    """שם מנורמל -> גרסה מותקנת בסביבה (best-effort, לעולם לא זורק)."""
    try:
        return {
            normalize_package_name(package["name"]): package.get("version", "")
            for package in installed_packages()
        }
    except Exception:                                    # pragma: no cover
        return {}


def parse_requirements(text: str, installed: dict[str, str] | None = None) -> dict:
    """
    פרסור הצהרת התלויות לקבוצות ייעוד + כרטיס לכל חבילה.

    כל הערה שצמודה לשורת תלות (בלי שורה ריקה ביניהן) היא הרציונל שלה,
    וכשכמה תלויות מופיעות אחרי אותו בלוק הערות — הרציונל משותף לכולן
    (כך זה כתוב בקובץ: fastapi/uvicorn/httpx/markdown חולקות הסבר אחד).
    שורה ריקה מפרידה בין "הערה כללית" לבין רציונל של חבילה, ולכן היא
    מאפסת את הצבירה — אחרת הוראות ההתקנה שבראש הקובץ היו נדבקות לחבילה
    הראשונה. קובץ ריק/חסר מוחזר כרשימת קבוצות ריקה, לא כחריגה.
    """
    versions = installed if installed is not None else _installed_versions()
    groups: list[dict] = []
    current: dict | None = None
    pending: list[str] = []   # בלוק ההערות שנצבר כרגע
    shared = ""               # הרציונל שחל על רצף התלויות הנוכחי
    after_requirement = False

    def _group(title: str) -> dict:
        block = {"title_he": title, "packages": []}
        groups.append(block)
        return block

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        header = _GROUP_HEADER_RE.match(line)
        if header:
            current = _group(_group_title_he(header.group(1)))
            pending, shared, after_requirement = [], "", False
            continue
        if not line:
            pending = []          # שורה ריקה מסיימת בלוק הערות
            continue
        if line.startswith("#"):
            if after_requirement:  # בלוק חדש — לא ממשיך את הרציונל הקודם
                pending, shared = [], ""
            comment = line.lstrip("#").strip()
            if comment:
                pending.append(comment)
            after_requirement = False
            continue
        if line.startswith("-"):   # דגלי pip (-r / --prefer-binary)
            continue
        match = _REQUIREMENT_LINE_RE.match(line.split("#", 1)[0].strip())
        if not match:
            continue
        if pending:
            shared = " ".join(pending)
            pending = []
        after_requirement = True
        if current is None:
            current = _group(DEFAULT_REQUIREMENT_GROUP_HE)
        name, extras, spec = match.group(1), match.group(2) or "", match.group(3)
        installed_version = versions.get(normalize_package_name(name), "")
        current["packages"].append({
            "name": name,
            "extras": extras,
            "version": _version_tag_he(spec),
            "installed_version": installed_version,
            "installed": bool(installed_version),
            "summary_he": _package_summary(name, shared),
            "rationale_he": " ".join(shared.split()),
        })

    groups = [group for group in groups if group["packages"]]
    # רציונל שמופיע ביותר מחבילה אחת הוא הסבר של קבוצת תלויות — התצוגה
    # אומרת זאת במקום להציג אותו כאילו הוא של החבילה הבודדת.
    shared_counts: dict[str, int] = {}
    for group in groups:
        for package in group["packages"]:
            text = package["rationale_he"]
            if text:
                shared_counts[text] = shared_counts.get(text, 0) + 1
    for group in groups:
        for package in group["packages"]:
            package["rationale_shared"] = (
                shared_counts.get(package["rationale_he"], 0) > 1
            )
    rows = [package for group in groups for package in group["packages"]]
    summary = {
        "total": len(rows),
        "groups": len(groups),
        "pinned": sum(1 for row in rows if row["version"]["kind"] == "pinned"),
        "ranged": sum(1 for row in rows if row["version"]["kind"] == "range"),
        "installed": sum(1 for row in rows if row["installed"]),
    }
    return {"groups": groups, "summary": summary}


def load_requirements(path: Path | None = None) -> dict:
    """דרישות המערכת המפורסרות + שורת הסבר על הסביבה שנסרקה."""
    target = path if path is not None else PROJECT_ROOT / "llm_requirements.txt"
    text = _read_text(target)
    payload = parse_requirements(text or "")
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    payload["environment_he"] = (
        f"הגרסאות המותקנות נקראות מהסביבה שמריצה את השרת (Python "
        f"{python_version}) בכל פתיחה — לא מרשימה שמורה."
    )
    payload["empty"] = not payload["groups"]
    payload["message_he"] = "" if payload["groups"] else (
        "המסמך ריק — לא נמצאו תלויות מוצהרות."
    )
    return payload


def parse_requirement_names(text: str) -> list[str]:
    """
    שמות החבילות המוצהרות ב-llm_requirements.txt (בסדר הופעתן).

    הקובץ הוא בעיקר הערות בעברית עם הרציונל לכל קיבוע, ולכן הפרסור פשוט
    בכוונה: מתעלם מהערות, משורות ריקות ומדגלי pip, ולוקח את השם שלפני
    סימן הגרסה/ה-extra.
    """
    names: list[str] = []
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name = re.split(r"[\[=<>!~;\s]", line, maxsplit=1)[0]
        if name:
            normalized = normalize_package_name(name)
            if normalized not in names:
                names.append(normalized)
    return names


# דרגות ההצהרה של חבילה, מהחזקה לחלשה. הן עונות על שאלה שהסיווג לבדו
# אינו עונה עליה: *כמה טוב* אנחנו יודעים מה הרישיון. מיפוי מאומת בסביבה
# הזו: 62 מצהירות ב-SPDX, 66 ב-classifier, 19 בטקסט חופשי, 1 בכלל לא.
DECLARATION_LABELS_HE = {
    "spdx": "SPDX (License-Expression)",
    "classifier": "classifier רשמי",
    "free_text": "טקסט חופשי בלבד",
    "verified": "אומת ידנית",
    "none": "לא מוצהר",
}
DECLARATION_ORDER = ("spdx", "classifier", "free_text", "verified", "none")

# מתי שדה License החופשי הוא בעצם *כל נוסח הרישיון* שנדחס לשדה מטא-דאטה
# (קורה ב-numpy, pandas, scipy, altair ואחרות). במקרה כזה השורה הראשונה
# היא "Copyright (c) ... All rights reserved" — כלומר תצוגה מבלבלת וגם
# רעש לסיווג — ולכן כשיש classifier רשמי הוא מועדף עליה.
_FULL_TEXT_MIN_CHARS = 80


def _license_fields(metadata) -> dict:
    """
    טקסט הרישיון של חבילה + דרגת ההצהרה שלה. {"raw", "declaration"}.

    סדר העדפה מכוון:
      1. `License-Expression` (SPDX) — ניסוח מלא ומדויק של כל הרישיונות,
         ולכן כשהוא קיים הוא לבדו נלקח: גם הסיווג מדויק וגם התצוגה
         קריאה ("MPL-2.0 AND MIT" במקום שלוש שורות classifier חוזרות).
      2. classifier רשמי של "License ::" — אוצר מילים סגור של PyPI.
      3. שדה License חופשי — לרוב מחרוזת SPDX ("MIT"), אבל לפעמים כל
         הנוסח; אז נלקחות עד שלוש השורות הראשונות בלבד.
    **הסיווג נשען על מטא-דאטה בלבד ולא על קריאת קובצי הרישיון עצמם.**
    זו החלטה, לא חיסכון: נוסח MPL-2.0 מגדיר בתוכו "Secondary License"
    ומזכיר במפורש את ה-GNU GPL/LGPL/AGPL (אומת ב-orjson, שורות 68-69
    בקובץ LICENSE-MPL-2.0 שלו), ולכן סורק תמים שקורא קובצי רישיון היה
    מסמן חבילות MPL-2.0 כקופילפט חזק. מטא-דאטה שהחבילה הצהירה עליה היא
    המקור האמין; קובץ רישיון נקרא רק בבדיקה ידנית מתועדת.
    """
    def field(name: str) -> str:
        try:
            return str(metadata.get(name) or "").strip()
        except Exception:
            return ""

    expression = field("License-Expression")
    if expression:
        return {"raw": expression.splitlines()[0][:120], "declaration": "spdx"}

    try:
        classifiers = [
            str(item).rsplit("::", 1)[-1].strip()
            for item in (metadata.get_all("Classifier") or [])
            if str(item).startswith("License ::")
        ]
    except Exception:
        classifiers = []
    free_text = field("License")
    dumped_full_text = len(free_text) >= _FULL_TEXT_MIN_CHARS or "\n" in free_text

    parts: list[str] = []
    if free_text and not (classifiers and dumped_full_text):
        # שורה אחת = מחרוזת רישיון; נוסח שלם בלי classifier -> עד 3 שורות
        lines = [line.strip() for line in free_text.splitlines() if line.strip()]
        parts.append(" ".join(lines[:3])[:200] if dumped_full_text else lines[0][:120])
    parts += classifiers

    seen: set[str] = set()
    unique = [
        part for part in parts
        if part and part.lower() not in seen and not seen.add(part.lower())
    ]
    if classifiers:
        declaration = "classifier"
    elif free_text:
        declaration = "free_text"
    else:
        declaration = "none"
    return {"raw": " · ".join(unique), "declaration": declaration}


def _bundled_license_files(dist) -> int:
    """
    כמה קובצי רישיון *נוספים* החבילה מצרפת (רישיונות של תלויות מוטמעות).

    למה זה מעניין: חבילה שמגיעה עם בינארי בנוי מצרפת את הרישיונות של מה
    שנבנה לתוכו — pypdfium2 מצרפת 29 קבצים כאלה (PDFium, FreeType, ICU,
    zlib...), ו-pip מצרפת 20 של החבילות ש-vendored בתוכה. המספר מוצג
    כמידע בלבד, בלי לגזור ממנו סיווג: ראה ההסבר ב-_license_fields למה
    קריאת נוסח הרישיונות אינה מקור אמין לסיווג אוטומטי.
    """
    try:
        base = getattr(dist, "_path", None)
        if base is None:
            return 0
        base = Path(base)
        # נסרקת רק תיקיית ה-licenses/ של החבילה (אם יש) ולא כל dist-info:
        # rglob על כל החבילות עלה ~0.5s לבקשה, וכל מה שמעניין יושב שם.
        # הקבצים בשורש dist-info או ישירות ב-licenses/ הם הרישיון של
        # החבילה עצמה; מה שעמוק מזה הוא של הספריות שנבנו לתוכה — ולכן
        # נספר לפי *מיקום*, לא לפי שם הקובץ: pypdfium2 קוראת להם
        # "freetype.txt" ו-"zlib.txt", בלי המילה license בשם.
        count = 0
        for directory in base.glob("[Ll][Ii][Cc][Ee][Nn][SsCc]*"):
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if path.is_file() and len(path.relative_to(base).parts) > 2:
                    count += 1
                    if count >= 999:
                        return count
        return count
    except Exception:
        return 0


def installed_packages() -> list[dict]:
    """
    החבילות המותקנות בסביבה הנוכחית + טקסט הרישיון של כל אחת.

    לעולם לא זורק: חבילה עם מטא-דאטה פגומה נכללת בלי רישיון (ותסווג
    כ"לא מזוהה"), וכשל בסריקה עצמה מחזיר רשימה ריקה.
    """
    try:
        from importlib.metadata import distributions
    except Exception:                                    # pragma: no cover
        return []
    found: dict[str, dict] = {}
    try:
        dists = list(distributions())
    except Exception:                                    # pragma: no cover
        return []
    for dist in dists:
        try:
            metadata = dist.metadata
            name = str(metadata.get("Name") or "").strip()
            if not name:
                continue
            key = normalize_package_name(name)
            if key in found:                             # התקנה כפולה
                continue
            fields = _license_fields(metadata)
            found[key] = {
                "name": name,
                "version": str(getattr(dist, "version", "") or ""),
                "license_raw": fields["raw"],
                "declaration": fields["declaration"],
                "bundled_licenses": _bundled_license_files(dist),
            }
        except Exception:
            continue
    return [found[key] for key in sorted(found)]


# ── רישיונות שאומתו ידנית ────────────────────────────────────────────────
# הטבלה הזו קיימת בגלל מקרה אמיתי אחד: crewai 1.6.1 **אינה מצהירה על
# רישיון בשום מקום שאפשר לסרוק אוטומטית** — אין License, אין
# License-Expression, אין classifier של "License ::" ואין License-File
# ב-dist-info; גם PyPI מחזיר license: None, וקובץ הרישיון אינו נכלל
# ב-wheel. הסיבה: lib/crewai/pyproject.toml בתג 1.6.1 (הקובץ שבונה את
# החבילה) פשוט חסר שדה license. זו השמטה באריזה, לא אי-בהירות ברישוי:
# בשורש המאגר, באותו תג, יש קובץ LICENSE שהוא נוסח MIT מלא, וה-README
# שנשלח *בתוך* החבילה מצהיר MIT.
#
# הכללים שהופכים את זה למכניזם בטוח ולא לפינה שבה נחות עובדות שגויות:
#   1. **מטא-דאטה גוברת תמיד.** העקיפה נכנסת לפעולה רק כשהסיווג
#      האוטומטי יצא "לא מזוהה". אם גרסה עתידית תצהיר GPL — ההצהרה
#      תנצח, והחבילה תסומן כקופילפט חזק (נבדק בסוויטה).
#   2. **אין עקיפה בלי ראיה.** כל רשומה נושאת את הנוסח שאומת ואת
#      הקישור אליו, וזה מוצג בתצוגה — לא נעלם בקוד.
#   3. התצוגה מסמנת את השורה "אומת ידנית", כדי שההבדל בין "החבילה
#      הצהירה" לבין "מישהו בדק" יישאר גלוי.
VERIFIED_LICENSES: dict[str, dict] = {
    "crewai": {
        "license": "MIT",
        "evidence_he": (
            "אומת ידנית: קובץ LICENSE בשורש המאגר crewAIInc/crewAI בתג "
            "1.6.1 הוא נוסח MIT מלא (Copyright (c) 2025 crewAI, Inc.), "
            "וה-README שנשלח בתוך החבילה מצהיר MIT. מטא-דאטת החבילה עצמה "
            "אינה כוללת שדה רישיון — השמטה באריזה."
        ),
        "source_url": "https://github.com/crewAIInc/crewAI/blob/1.6.1/LICENSE",
    },
}


def _packages_he(count: int) -> str:
    """ניסוח עברי תקין למספר חבילות (יחיד/רבים) — התצוגה בעברית."""
    return "חבילה אחת" if count == 1 else f"{count} חבילות"


def build_license_report(packages: list[dict] | None = None,
                         declared: list[str] | None = None) -> dict:
    """
    הדוח המלא: סיווג כל חבילה, סיכום כמותי, והתשובה לשאלת הזכויות.

    `packages`/`declared` מוזרקים בבדיקות (כולל רשימה ריקה ורישיון לא
    מזוהה); בלעדיהם נסרקת הסביבה החיה ו-llm_requirements.txt.
    """
    if packages is None:
        packages = installed_packages()
    if declared is None:
        declared = parse_requirement_names(
            _read_text(PROJECT_ROOT / "llm_requirements.txt") or ""
        )
    declared_set = set(declared)

    grouped: dict[str, list[dict]] = {key: [] for key in LICENSE_CATEGORIES}
    installed_names = set()
    verified_count = 0
    for package in packages:
        raw = package.get("license_raw", "")
        verdict = classify_license(raw)
        key = normalize_package_name(package.get("name", ""))
        installed_names.add(key)
        declaration = package.get("declaration") or (
            "none" if not raw else "free_text"
        )
        row = {
            "name": package.get("name", ""),
            "version": package.get("version", ""),
            "license_raw": raw or "—",
            "category": verdict["category"],
            "matched_he": verdict["matched_he"],
            "declared": key in declared_set,
            "verified": False,
            "source_url": "",
            "declaration": declaration,
            "declaration_he": DECLARATION_LABELS_HE.get(declaration, declaration),
            "bundled_licenses": int(package.get("bundled_licenses") or 0),
        }
        # עקיפה מאומתת — רק כשהמטא-דאטה שותקת (ראה VERIFIED_LICENSES).
        override = VERIFIED_LICENSES.get(key)
        if override and verdict["category"] == "unknown":
            row["category"] = classify_license(override["license"])["category"]
            row["license_raw"] = f"{override['license']} (אומת ידנית)"
            row["matched_he"] = override["evidence_he"]
            row["source_url"] = override.get("source_url", "")
            row["verified"] = True
            row["declaration"] = "verified"
            row["declaration_he"] = DECLARATION_LABELS_HE["verified"]
            verified_count += 1
        grouped[row["category"]].append(row)

    summary = {key: len(items) for key, items in grouped.items()}
    summary["total"] = len(packages)
    summary["declared"] = len(declared_set)
    summary["verified"] = verified_count

    # איכות ההצהרה — התשובה ל"על מה הסיווג נשען", בנפרד מהסיווג עצמו.
    all_rows = [row for items in grouped.values() for row in items]
    declaration_summary = {
        tier: sum(1 for row in all_rows if row["declaration"] == tier)
        for tier in DECLARATION_ORDER
    }
    bundling = sorted(
        ({"name": row["name"], "count": row["bundled_licenses"]}
         for row in all_rows if row["bundled_licenses"] > 1),
        key=lambda item: -item["count"],
    )[:10]
    categories = [
        {
            "key": key,
            **{field: value for field, value in LICENSE_CATEGORIES[key].items()},
            "count": len(grouped[key]),
            "packages": sorted(grouped[key], key=lambda item: item["name"].lower()),
        }
        for key in CATEGORY_DISPLAY_ORDER
    ]
    flagged = [
        package
        for key in ("strong_copyleft", "unknown")
        for package in grouped[key]
    ]
    # חבילה שמוצהרת ב-requirements אך אינה מותקנת — הרישיון שלה לא נבדק.
    declared_missing = sorted(declared_set - installed_names)

    if not packages:
        verdict_he = ("לא נמצאו חבילות מותקנות לסריקה — אין על מה לדווח.")
        verdict_tone = "unknown"
    elif summary["strong_copyleft"]:
        verdict_he = (
            f"נמצאו {_packages_he(summary['strong_copyleft'])} בקופילפט חזק "
            "(GPL/AGPL) — דגל אדום: יש לבדוק אותן משפטית לפני הפצה."
        )
        verdict_tone = "danger"
    elif summary["unknown"]:
        verdict_he = (
            "אין בפרויקט אף חבילה בקופילפט חזק (GPL/AGPL). "
            f"{_packages_he(summary['unknown'])} בלי רישיון מזוהה "
            "במטא-דאטה — לבדיקה ידנית; שאר החבילות בשימוש חופשי."
        )
        verdict_tone = "warn"
    else:
        verdict_he = (
            "כל החבילות בשימוש חופשי: אין GPL/AGPL ואין רישיון לא מזוהה."
        )
        if verified_count:
            # שקיפות: "הכול בסדר" שנשען על בדיקה ידנית חייב לומר זאת.
            verdict_he += (
                f" ב-{_packages_he(verified_count)} הרישיון אינו מוצהר "
                "במטא-דאטה ואומת ידנית מול המאגר — השורה מסומנת בהתאם."
            )
        verdict_tone = "ok"

    return {
        "summary": summary,
        "categories": categories,
        "flagged": flagged,
        "declared_missing": declared_missing,
        "declaration_summary": declaration_summary,
        "declaration_labels_he": DECLARATION_LABELS_HE,
        "declaration_note_he": (
            "הסיווג נשען על מה שהחבילה מצהירה על עצמה במטא-דאטה, ולא על "
            "קריאת קובץ הרישיון שלה: נוסח MPL-2.0 מזכיר בתוכו את ה-GNU GPL "
            "(הגדרת \"Secondary License\"), ולכן סורק שקורא נוסחים היה מסמן "
            "חבילות MPL-2.0 כקופילפט חזק. חבילה שאינה מצהירה כלל מסומנת "
            "לבדיקה ידנית."
        ),
        "bundling": bundling,
        "bundling_note_he": (
            "חבילות שמגיעות עם בינארי בנוי מצרפות את הרישיונות של הספריות "
            "שנבנו לתוכן. המספר הוא מידע בלבד ואינו משנה סיווג — הרכיבים "
            "המצורפים אינם בהכרח נכללים ב-wheel של הפלטפורמה שלנו."
        ),
        "verdict_he": verdict_he,
        "verdict_tone": verdict_tone,
        "available": True,
        "empty": not packages,
        "message_he": "" if packages else
                      "לא נמצאו חבילות מותקנות בסביבה שמריצה את השרת.",
    }


# מדיניות התוכן והנכסים של הפרויקט. לא רישיון תוכנה — זכויות *תוכן*, וזו
# השאלה השנייה שהתצוגה צריכה לענות עליה. הטענות כאן נאמרות יחד עם
# האימות האוטומטי שלהן (מספר המסמכים שבהם נמצאה שורת "מקור:" עם קישור),
# כדי שהקורא לא יצטרך להאמין למילה.
CONTENT_POLICY_HE = (
    "מאגר הידע של אן נכתב מחדש בעברית על בסיס מקורות רפואיים "
    "(שירותי בריאות כללית, מכבי, מאוחדת, מגן דוד אדום ואחרים) — הוא אינו "
    "העתקה של תוכן המקורות. כל מסמך מפנה למקור שממנו נגזר, בשורת "
    "\"מקור:\" עם קישור."
)
# מצב הזכויות של האיורים. הניסוח מדויק בכוונה בשני הכיוונים: הוא אומר
# *איך* נוצרו (כלי AI ליצירת תמונות + עריכה והתאמה ידנית) ולמה אין עליהם
# זכויות של אחרים (הם אינם נגזרים מיצירה של צד שלישי) — ובאותה נשימה
# אינו טוען בעלות עליהם. מעמד הזכויות בתוצרי AI אינו אחיד בין מדינות,
# וטענת בעלות כאן הייתה הצהרה משפטית שאין לה כיסוי, בדיוק הסוג שהעמוד
# הזה נמנע ממנו במקומות האחרים ("טעון אימות" במקום ניחוש).
ILLUSTRATIONS_POLICY_HE = (
    "האיורים המודרכים הופקו במיוחד עבור הפרויקט הזה בעזרת כלי AI ליצירת "
    "תמונות, ולאחר מכן עברו עריכה והתאמה ידנית: כיתובים בעברית, התאמה "
    "לפלטת הצבעים של אן ולשלבי הטיפול שהם מדגימים. הם אינם מבוססים על "
    "יצירות של צד שלישי ואינם העתקה שלהן, ולכן אין עליהם זכויות של "
    "אחרים ואין תלות ברישיון חיצוני — ומנגד, גם לא נטענת כאן בעלות "
    "עליהם. הם מוצגים מרשימה סגורה ומאומתת, והם המחשה חינוכית בלבד "
    "ולא חומר רפואי רשמי."
)
LEGAL_DISCLAIMER_HE = (
    "זהו סיכום טכני אוטומטי לצורכי תיעוד ואינו ייעוץ משפטי. הסיווג נגזר "
    "ממטא-דאטה שהחבילות מפרסמות על עצמן, ולכן הוא עשוי להיות חסר או לא "
    "מדויק. לפני החלטה מסחרית או הפצה — יש לאמת מול הרישיון המקורי של כל "
    "חבילה ולהיוועץ בגורם משפטי."
)


# תמונות ההדגמה שבריפו (assets/demo/). עד עכשיו ההדגמה עבדה רק עם תמונה
# שהמשתמש מעלה בזמן ההרצה, בדיוק כדי שלא תיכנס לריפו תמונה עם זכויות של
# מישהו אחר. התמונה שנוספה נוצרה ב-AI במיוחד עבור הפרויקט, ולכן היא
# עומדת באותו כלל של האיורים — ומכיוון שדף הרישיונות מצהיר על *כל* נכסי
# התוכן, היא מוצהרת כאן במפורש ולא נשארת נכס שקוף.
DEMO_IMAGES_DIR = "assets/demo"
DEMO_IMAGES_POLICY_HE = (
    "תמונות ההדגמה שמצורפות אוטומטית בתרחישי ההדגמה הופקו בעזרת כלי AI "
    "ליצירת תמונות במיוחד עבור הפרויקט הזה. הן אינן צילום של אדם אמיתי "
    "ואינן מבוססות על יצירות של צד שלישי, ולכן אין עליהן זכויות של "
    "אחרים ואין תלות ברישיון חיצוני — ומנגד, גם לא נטענת כאן בעלות "
    "עליהן. הן ממחשות תרחיש לימודי בלבד ואינן חומר רפואי."
)


def build_demo_image_rights(root: Path | None = None) -> dict:
    """מצב הזכויות של תמונות ההדגמה — נמדד מהתיקייה בזמן אמת."""
    directory = root if root is not None else PROJECT_ROOT / DEMO_IMAGES_DIR
    try:
        files = sorted(
            item.name for item in directory.iterdir()
            if item.is_file()
            and item.suffix.lower() in DEMO_IMAGE_SUFFIXES
        )
    except OSError:
        files = []
    return {
        "policy_he": DEMO_IMAGES_POLICY_HE,
        "total": len(files),
        "evidence_he": (
            "אימות אוטומטי: "
            + ("תמונת הדגמה אחת" if len(files) == 1
               else f"{len(files)} תמונות הדגמה")
            + " בתיקיית הנכסים."
            if files else
            "אין תמונות הדגמה בפרויקט — התרחישים משתמשים בתמונה שהמשתמש "
            "מעלה בזמן ההרצה."
        ),
    }


def build_content_rights(data_dir: Path | None = None,
                         catalog_path: Path | None = None) -> dict:
    """
    מצב הזכויות של התוכן והנכסים — מאגר הידע והאיורים.

    כל המספרים נמדדים בזמן אמת מאותם מקורות חיים שמציגי "מקורות הידע"
    ו"סטוריבורד האיורים" קוראים, כדי שלא תיווצר טענה שמתיישנת. שדה
    ייעודי בקטלוג (`_attribution`) נשמר אם הוסיפו אותו — ואם אינו קיים,
    התצוגה אומרת במפורש שהמקור לא נרשם, ולא ממציאה אותו.
    """
    knowledge = load_knowledge_sources(data_dir)
    documents = [
        document
        for topic in knowledge.get("topics", [])
        for document in topic["documents"]
    ]
    with_source = sum(1 for document in documents if document.get("source_url"))
    gallery = load_illustration_gallery(catalog_path)
    images_present = sum(
        1
        for category in gallery.get("categories", [])
        for item in category["items"]
        if item.get("image_exists")
    )

    attribution = ""
    raw = _read_text(catalog_path if catalog_path is not None
                     else ILLUSTRATIONS_JSON)
    if raw:
        try:
            attribution = str(json.loads(raw).get("_attribution") or "").strip()
        except (json.JSONDecodeError, AttributeError):
            attribution = ""

    return {
        "knowledge": {
            "policy_he": CONTENT_POLICY_HE,
            "documents": len(documents),
            "with_source": with_source,
            "totals": knowledge.get("totals", {}),
            "evidence_he": (
                f"אימות אוטומטי: {with_source} מתוך {len(documents)} מסמכי "
                "הידע כוללים שורת מקור עם קישור."
                if documents else
                "לא נמצאו מסמכי ידע במאגר — אין מה לאמת."
            ),
            "complete": bool(documents) and with_source == len(documents),
        },
        "demo_images": build_demo_image_rights(),
        "illustrations": {
            "policy_he": ILLUSTRATIONS_POLICY_HE,
            "total": gallery.get("total", 0),
            "images_present": images_present,
            "attribution_he": attribution,
            "recorded": bool(attribution),
            "evidence_he": (
                attribution if attribution else
                "מקור האיורים אינו רשום בקטלוג האיורים — מומלץ לרשום "
                "אותו שם כדי שהתצוגה תציג אותו כאן. עד אז מצב הזכויות "
                "טעון אימות."
            ),
        },
    }


def load_license_report(requirements_path: Path | None = None) -> dict:
    """כל מה שתצוגת הרישיונות מציגה: חבילות, תוכן, נכסים וסייג משפטי."""
    declared = parse_requirement_names(
        _read_text(requirements_path if requirements_path is not None
                   else PROJECT_ROOT / "llm_requirements.txt") or ""
    )
    report = build_license_report(declared=declared)
    report["content"] = build_content_rights()
    report["disclaimer_he"] = LEGAL_DISCLAIMER_HE
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    report["environment_he"] = (
        f"הסריקה חיה: החבילות נקראות מהסביבה שמריצה את השרת (Python "
        f"{python_version}) בכל פתיחה, וההצהרות מהצהרת התלויות של הפרויקט."
    )
    return report


# ── רנדרר: Markdown -> HTML ממותג (בתוך iframe) ──────────────────────────
_DOC_PAGE_CSS = """
  :root { color-scheme: light; }
  body {
    margin: 0;
    padding: 28px clamp(16px, 5vw, 56px) 64px;
    font-family: "Heebo", "Rubik", "Arial Hebrew", sans-serif;
    background: var(--bg-page, #FFF8F2);
    color: var(--text-primary, #4A3A4F);
    line-height: 1.75;
  }
  .doc-md { max-width: 900px; margin: 0 auto; }
  .doc-md h1, .doc-md h2, .doc-md h3, .doc-md h4 {
    color: var(--plum-600, #4A3A4F);
    line-height: 1.35;
    margin: 1.6em 0 0.5em;
  }
  .doc-md h1 { font-size: 1.7rem; margin-top: 0; }
  .doc-md h2 {
    font-size: 1.3rem;
    padding-bottom: 6px;
    border-bottom: 2px solid var(--sand-200, #F4E4D2);
  }
  .doc-md h3 { font-size: 1.08rem; }
  .doc-md a { color: var(--link, #D85F45); }
  .doc-md code {
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.86em;
    background: var(--sand-100, #FBF0E2);
    border: 1px solid var(--border, #F0D9C9);
    border-radius: 6px;
    padding: 1px 5px;
    direction: ltr;
    unicode-bidi: embed;
  }
  .doc-md pre {
    direction: ltr;
    text-align: left;
    background: #FFFFFF;
    border: 1px solid var(--border, #F0D9C9);
    border-inline-start: 4px solid var(--coral-400, #F2876F);
    border-radius: 12px;
    padding: 14px 16px;
    overflow-x: auto;
  }
  .doc-md pre code { background: none; border: 0; padding: 0; }
  .doc-md blockquote {
    margin: 1.2em 0;
    padding: 10px 16px;
    background: #FFFDFB;
    border: 1px solid var(--border, #F0D9C9);
    border-inline-start: 4px solid var(--gold-400, #E6A95C);
    border-radius: 12px;
    color: var(--text-muted, #8C7670);
  }
  .doc-md table {
    width: 100%;
    border-collapse: collapse;
    margin: 1.2em 0;
    font-size: 0.92rem;
  }
  .doc-md th, .doc-md td {
    border: 1px solid var(--border, #F0D9C9);
    padding: 8px 10px;
    text-align: start;
  }
  .doc-md th { background: var(--sand-100, #FBF0E2); }
  .doc-md tr:nth-child(even) td { background: #FFFDFB; }
  .doc-md hr { border: 0; border-top: 1px solid var(--sand-200, #F4E4D2); margin: 2em 0; }
  .doc-md img { max-width: 100%; }
  .doc-empty {
    max-width: 760px;
    margin: 40px auto;
    padding: 18px 20px;
    background: #FFFFFF;
    border: 1px solid var(--border, #F0D9C9);
    border-inline-start: 4px solid var(--coral-400, #F2876F);
    border-radius: 14px;
    color: var(--text-muted, #8C7670);
  }
"""


def _doc_page(title: str, body_html: str,
              lang: str = "he", direction: str = "rtl") -> str:
    """
    עטיפת HTML ממותגת למסמך שמוצג ב-iframe (וגם להצהרת הנגישות הציבורית).

    ה-CSS נטען מ-/assets/colors.css (אותו origin) כדי שהמסמך ישתמש
    באותם טוקנים של שאר הממשק, עם ערכי נפילה בתוך גיליון העמוד למקרה
    שהקובץ לא נטען.

    בתחתית מוזרק הקרדיט מ-credit.py — כאן דווקא בתוך העמוד עצמו ולא
    במסגרת שמסביבו, כי זה העמוד ש*מודפס*: הדפסה מוציאה את תוכן ה-iframe
    בלבד, וגיליון הקרדיט כולל כלל @media print שמשאיר אותו שם.

    lang/direction מגיעים מה-DocSpec ומתארים את שפת המסמך. הקרדיט עצמו
    כופה על עצמו direction: rtl ב-CREDIT_CSS, וגושי הקוד כופים ltr — כך
    ששני הכיוונים נכונים גם בעמוד אנגלי.
    """
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{html_lib.escape(lang, quote=True)}" '
        f'dir="{html_lib.escape(direction, quote=True)}">\n<head>\n'
        '<meta charset="utf-8" />\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        f"<title>{html_lib.escape(title)}</title>\n"
        '<link rel="stylesheet" href="/assets/colors.css" />\n'
        f"<style>{_DOC_PAGE_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body_html}\n"
        f"{credit_html(with_style=True)}\n"
        "</body>\n</html>\n"
    )


def markdown_to_html(text: str) -> str:
    """
    המרת Markdown ל-HTML.

    התוספים הם המינימום שהמסמכים של הפרויקט באמת משתמשים בו: טבלאות,
    גושי קוד מגודרים ורשימות שמכבדות מספור. אין הדגשת תחביר (היא
    דורשת pygments — תלות נוספת בלי תמורה אמיתית כאן).
    """
    import markdown as markdown_lib  # ייבוא עצל — נדרש רק לרנדרר הזה

    return markdown_lib.markdown(
        text or "",
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html",
    )


def document_page_html(key: str) -> str:
    """
    ה-HTML שמוגש ל-iframe של המציג (רק עבור kind של html/markdown).

    לעולם לא זורק על תוכן: קובץ חסר או ריק מוחזר כעמוד ממותג עם הודעה
    בעברית. מפתח לא מוכר או סוג לא מתאים -> UnknownDocument (404).
    """
    spec = get_spec(key)
    if spec.kind not in {"html", "markdown"}:
        raise UnknownDocument(key)

    text = _read_text(spec.source)
    if text is None:
        return _doc_page(
            spec.title,
            '<div class="doc-empty">מקור המסמך אינו קיים בפרויקט. '
            "המסמך יוצג אוטומטית ברגע שיחזור למקומו.</div>",
        )
    if not text.strip():
        return _doc_page(
            spec.title,
            '<div class="doc-empty">המסמך ריק — אין מה להציג.</div>',
        )
    if spec.kind == "html":
        # קובץ HTML שלם מוגש כמות שהוא — הוא כבר מעוצב, וה-iframe מבודד
        # אותו מהעמוד. אין כאן עותק: הקריאה היא מהדיסק בכל בקשה.
        return text
    return _doc_page(
        spec.title,
        f'<article class="doc-md">{markdown_to_html(text)}</article>',
        lang=spec.page_lang,
        direction=spec.page_dir,
    )


# ── ה-API שהשרת חושף ─────────────────────────────────────────────────────
def document_cards(token: str = "") -> list[dict]:
    """
    כרטיסי המסמכים לרשת באזור המנהל — כולל מצב זמינות וקישורי פעולה.

    ה-token נכנס ל-query של הקישורים כי ה-iframe וההורדה אינם יכולים
    לשלוח כותרות — מקובל בהיקף הזה, שבו הטוקן פותח מסמכי פרויקט בלבד
    (ראה ההערה ב-server/app.py).
    """
    suffix = f"?token={token}" if token else ""
    cards = []
    for spec in DOCUMENTS.values():
        exists = _source_exists(spec)
        download = spec.download_path
        has_download = bool(download and download.exists())
        cards.append({
            "key": spec.key,
            "title": spec.title,
            "description": spec.description,
            "kind": spec.kind,
            "file_name": spec.source.name,
            "exists": exists,
            "size_he": size_he(spec.source) if exists and spec.source.is_file() else "",
            "live_note_he": spec.live_note_he,
            "view_url": f"/api/admin/doc/{spec.key}/view{suffix}",
            "page_url": (f"/api/admin/doc/{spec.key}/page{suffix}"
                         if spec.kind in {"html", "markdown"} else ""),
            "download_url": (f"/api/admin/doc/{spec.key}{suffix}"
                             if has_download else ""),
            "download_name": download.name if has_download else "",
        })
    return cards


def document_view(key: str, token: str = "") -> dict:
    """
    המטען שהמציג בדפדפן מקבל: סוג המסמך + התוכן המפורסר שלו.

    לכל סוג יש מפתח תוכן משלו, והצד הלקוח בוחר רנדרר לפי `kind`. מסמך
    שמקורו חסר מוחזר עם available=false והודעה בעברית — הרנדרר מציג
    כרטיס הסבר, ולא מסך שבור.
    """
    spec = get_spec(key)
    suffix = f"?token={token}" if token else ""
    download = spec.download_path
    has_download = bool(download and download.exists())
    payload: dict = {
        "key": spec.key,
        "kind": spec.kind,
        "title": spec.title,
        "description": spec.description,
        "file_name": spec.source.name,
        "live_note_he": spec.live_note_he,
        "available": _source_exists(spec),
        "message_he": "",
        "download_url": (f"/api/admin/doc/{spec.key}{suffix}"
                         if has_download else ""),
        "download_name": download.name if has_download else "",
    }
    if not payload["available"]:
        payload["message_he"] = (
            "מקור המסמך אינו קיים בפרויקט. המסמך יוצג אוטומטית ברגע "
            "שיחזור למקומו."
        )
        return payload

    if spec.kind in {"html", "markdown"}:
        payload["page_url"] = f"/api/admin/doc/{spec.key}/page{suffix}"
        text = _read_text(spec.source)
        payload["empty"] = not (text or "").strip()
    elif spec.kind == "text":
        text = _read_text(spec.source) or ""
        payload["text"] = text
        payload["empty"] = not text.strip()
        if payload["empty"]:
            payload["message_he"] = "המסמך ריק — אין מה להציג."
    elif spec.kind == "requirements":
        payload.update(load_requirements(spec.source))
    elif spec.kind == "checklist":
        text = _read_text(spec.source) or ""
        plan = parse_test_plan(text)
        payload.update(plan)
        payload["empty"] = not plan["items"]
        if payload["empty"]:
            payload["message_he"] = (
                "לא נמצאו נקודות בדיקה ממוספרות במסמך."
            )
    elif spec.kind == "sources":
        knowledge = load_knowledge_sources(spec.source)
        payload.update(knowledge)
        payload["empty"] = not knowledge["topics"]
        if payload["empty"]:
            payload["message_he"] = "לא נמצאו מסמכי ידע במאגר."
    elif spec.kind == "gallery":
        gallery = load_illustration_gallery(spec.source)
        payload.update(gallery)
        payload["empty"] = not gallery["categories"]
        payload["available"] = gallery["available"]
    elif spec.kind == "scenarios":
        demo = load_demo_scenarios(spec.source)
        payload.update(demo)
        payload["empty"] = not demo["scenarios"]
        payload["available"] = demo["available"]
    elif spec.kind == "licenses":
        # שים לב: המקור של המסמך הזה הוא הצהרת התלויות, אבל הרישיונות
        # נסרקים מהסביבה — ולכן גם אם הקובץ חסר, הדוח עצמו עדיין תקף.
        report = load_license_report(spec.source)
        payload.update(report)
        payload["available"] = True
    return payload

"""
קרדיט ומיתוג אישי — **מקור האמת היחיד** לכיתוב, לקישורים ולאייקונים.

הכיתוב מופיע בכל משטחי הפרויקט: הצ'אט, אזור המנהל (שלוש התצוגות: כניסה,
לוח ומציג המסמכים — ובכללן מסך תרחישי ההדגמה), עמודי המסמכים הממותגים
שמוצגים ב-iframe ומודפסים, הצהרת הנגישות הציבורית, ושתי אפליקציות
ה-Streamlit. במקום לפזר את המשפט בעשרה קבצים, הוא מוגדר כאן פעם אחת
וכל צרכן פייתון מייבא אותו.

לצד הקובץ הזה קיים `web/credit.js`, שבונה את אותו קרדיט בדפדפן. הכפילות
נדרשת מסיבה טכנית אחת: דף HTML סטטי אינו יכול לקרוא מודול פייתון, וקריאת
JSON הייתה מוסיפה בקשת רשת — והדרישה היא שהקרדיט יעבוד גם אופליין. לכן
**בדיקת אופליין משווה את שני הקבצים מחרוזת-מחרוזת** (הטקסט, הקישורים,
תוויות ה-aria ונתיבי ה-SVG); כל סטייה מפילה את הסוללה, כך שבפועל יש
מקור אמת אחד.

האייקונים הם SVG מוטמע: אין CDN, אין גופן אייקונים, אין בקשת רשת אחת
נוספת, והכול עובד גם בלי חיבור לאינטרנט.
"""
from __future__ import annotations

# ── הטקסט ────────────────────────────────────────────────────────────────
AUTHOR_NAME_HE = "מאור דהן"
CREDIT_PREFIX_HE = "נבנה על ידי "
CREDIT_SUFFIX_HE = (
    " במסגרת קורס AI מטעם בית הספר למנהל עסקים של האוניברסיטה העברית"
)
CREDIT_TEXT_HE = f"{CREDIT_PREFIX_HE}{AUTHOR_NAME_HE}{CREDIT_SUFFIX_HE}"

# ── הקישורים ─────────────────────────────────────────────────────────────
LINKEDIN_URL = "https://www.linkedin.com/in/maordahan/"
GITHUB_URL = "https://github.com/maor125"

# rel="noopener noreferrer" הוא דרישת אבטחה ולא נוי: בלי noopener, הדף
# שנפתח מקבל הפניה ל-window.opener ויכול לנווט את החלון שלנו למקום אחר.
LINK_REL = "noopener noreferrer"
LINK_TARGET = "_blank"

# ── נגישות ───────────────────────────────────────────────────────────────
LINKEDIN_ARIA_HE = "פרופיל LinkedIn של מאור דהן"
GITHUB_ARIA_HE = "פרופיל GitHub של מאור דהן"

# שטח לחיצה מינימלי (WCAG 2.5.5 / 2.5.8) — האייקון עצמו קטן, אבל תיבת
# הלחיצה סביבו לא יורדת מ-44×44.
MIN_TAP_TARGET_PX = 44

# ── האייקונים (SVG מוטמע, viewBox 24×24, currentColor) ───────────────────
LINKEDIN_PATH = (
    "M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM2.98 8.98h4v12h-4z"
    "M9.5 8.98h3.83v1.64h.05c.53-.95 1.83-1.96 3.77-1.96 4.03 0 4.78 2.53 "
    "4.78 5.82v6.5h-4v-5.76c0-1.37-.03-3.14-1.96-3.14-1.96 0-2.26 1.5-2.26 "
    "3.04v5.86h-4z"
)
GITHUB_PATH = (
    "M12 .5C5.73.5.5 5.73.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56"
    "v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7"
    ".08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-"
    "1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.29 1.19-3.1-.12-"
    ".29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 "
    "3.17-1.18 3.17-1.18.63 1.59.23 2.76.12 3.05.74.81 1.18 1.84 1.18 3.1 0 "
    "4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5"
    " 11.5 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5z"
)

# ── CSS (משותף לעמודי המסמכים ול-Streamlit; בדפדפן מוזרק מ-credit.js) ────
# הצבעים הם טוקנים סמנטיים של הפרויקט, עם ערכי נפילה למקרה שגיליון
# הטוקנים לא נטען (עמוד מסמך שמוצג לבדו, למשל בהדפסה).
CREDIT_CSS = f"""
.anne-credit {{
  direction: rtl;
  text-align: center;
  margin: 18px auto 6px;
  font-size: 0.74rem;
  line-height: 1.9;
  color: var(--text-muted, #8C7670);
}}
.anne-credit a {{ color: var(--link, #B34A32); }}
.anne-credit-name {{ font-weight: 600; }}
.anne-credit-icons {{
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
}}
.anne-credit-icon {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: {MIN_TAP_TARGET_PX}px;
  min-height: {MIN_TAP_TARGET_PX}px;
  color: var(--text-muted, #8C7670);
  text-decoration: none;
}}
.anne-credit-icon:hover {{ color: var(--link, #B34A32); }}
.anne-credit-icon svg {{ width: 17px; height: 17px; fill: currentColor; }}
.anne-credit a:focus-visible {{
  outline: 2px solid var(--focus-ring, #B34A32);
  outline-offset: 2px;
  border-radius: 8px;
}}
/* הדפסה: הקרדיט הוא חלק מהמסמך המודפס, לא קישוט מסך. */
@media print {{
  .anne-credit {{
    display: block !important;
    color: #000 !important;
    page-break-inside: avoid;
  }}
  .anne-credit a {{ color: #000 !important; }}
}}
"""


def _icon_link(url: str, aria_label: str, path: str) -> str:
    return (
        f'<a class="anne-credit-icon" href="{url}" target="{LINK_TARGET}" '
        f'rel="{LINK_REL}" aria-label="{aria_label}">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
        f'<path d="{path}" /></svg></a>'
    )


def credit_html(with_style: bool = False) -> str:
    """
    הקרדיט כ-HTML מוכן להזרקה (שרת/Streamlit).

    with_style=True מצרף גם את גיליון הסגנון — נדרש בעמודי המסמכים
    הממותגים, שאינם טוענים את הגיליונות של הצ'אט.
    """
    markup = (
        '<p class="anne-credit">'
        f"{CREDIT_PREFIX_HE}"
        f'<a class="anne-credit-name" href="{LINKEDIN_URL}" '
        f'target="{LINK_TARGET}" rel="{LINK_REL}">{AUTHOR_NAME_HE}</a>'
        '<span class="anne-credit-icons">'
        f"{_icon_link(LINKEDIN_URL, LINKEDIN_ARIA_HE, LINKEDIN_PATH)}"
        f"{_icon_link(GITHUB_URL, GITHUB_ARIA_HE, GITHUB_PATH)}"
        "</span>"
        f"{CREDIT_SUFFIX_HE}"
        "</p>"
    )
    if with_style:
        return f"<style>{CREDIT_CSS}</style>\n{markup}"
    return markup

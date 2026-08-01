"""
שכבת ה-UI המשותפת לשתי אפליקציות ה-Streamlit של אן.

שתי אפליקציות נפרדות יושבות מעל *אותו* לוג שיחות אנונימי (storage/):
  * dashboard/app.py    — דשבורד הסקירה (פורט 8501 כברירת מחדל)
  * dashboard/ml_app.py — עמוד מודל החיזוי הלימודי (פורט 8502)

כל מה שמשותף להן — הפלטה, ה-CSS של המותג, כותרת ממותגת, גרף הקטגוריות,
טעינת הנתונים עם cache, בורר קובץ הלוג והמסננים — חי כאן ולא משוכפל.
הכלל: הקובץ הזה מכיל *רק* תצוגה וטעינה גנרית. כל אגרגציה של נתונים
שייכת ל-dashboard/data.py (pandas טהור, נבדק אופליין בלי שרת), וכל תוכן
ייעודי לאפליקציה אחת נשאר בקובץ שלה.

המודול הזה לא מייבא את ml/ — הדשבורד חייב לעלות גם בסביבה בלי
scikit-learn, והתלות הרכה מנוהלת ב-ml_app.py בלבד.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import altair as alt
import pandas as pd
import streamlit as st

from credit import credit_html
from dashboard.data import (
    PATH_HE,
    PATH_ORDER,
    TOPIC_HE,
    TOPIC_ORDER,
    filter_turns,
    load_turns_df,
)
from storage.synthetic import DEFAULT_SYNTH_DB
from storage.turn_log import (
    DEFAULT_DB_PATH,
    ENV_DB_VAR,
    LIVE_TABLE,
    SYNTHETIC_TABLE,
    init_db,
    resolve_target,
)

# ── פלטת האפליקציות ──────────────────────────────────────────────────────
# ערכת קטגוריות אחת בסדר קבוע, נגזרת ממשפחות המותג (קורל, לבנדר, זהב,
# מרווה, שזיף/יין) ומאומתת לנגישות. תחומים תופסים את חמשת המקומות;
# מסלולי ייעוץ את שלושת הראשונים — תמיד לפי מפתח הישות, לא לפי סדר הופעה.
CATEGORICAL = ("#D85F45", "#7C5BAD", "#C2832F", "#4E8A3C", "#9A4E6C")
TOPIC_COLORS = dict(zip(TOPIC_ORDER, CATEGORICAL))
PATH_COLORS = dict(zip(PATH_ORDER, CATEGORICAL[:3]))
# צבע קבוע לכל מודל חיזוי (לפי מפתח הישות, כמו התחומים והמסלולים).
# מודל הבסיס מקבל את הגוון השקט — הוא קו ייחוס, לא "סדרה" שווה-ערך.
MODEL_COLORS = {
    "logistic": CATEGORICAL[0],
    "random_forest": CATEGORICAL[1],
    "gradient_boosting": CATEGORICAL[2],
    "baseline": "#B6A088",
}
BRAND = "#F2876F"      # coral-400 — גרפים חד-סדרתיים (הזהות בתוויות הציר)
# קורל כהה — הגוון היחיד מהמשפחה שטקסט לבן עליו עומד ב-4.5:1 (5.33), אותו
# ערך של --btn-primary בפלטת הדפדפן. משמש למצב ה*פעיל* של מתג מקור הנתונים:
# מצב פעיל בקורל הבהיר עם טקסט לבן היה יורד ל-2.48 ונופל מהתקן.
BRAND_STRONG = "#B34A32"
EMERGENCY = "#C94F45"  # safety-600 — שמור לחירום בלבד, לעולם לא "סדרה 4"
INK = "#4A3A4F"        # plum-600 — טקסט
MUTED = "#8C7670"      # טקסט משני
GRID = "#F4E4D2"       # sand-200 — רשת שקטה

# ── נכסי המותג ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
LOGO = ASSETS_DIR / "Logo.png"           # הסמל הראשי (דיוקן + לוגוטייפ)
LOGO_FIGURE = ASSETS_DIR / "Logo_2.png"  # דמות מלאה — קישוט בסרגל הצד

# ── כתובות שתי האפליקציות ────────────────────────────────────────────────
# הדשבורד רץ בפורט ברירת המחדל של Streamlit (8501) ועמוד החיזוי בשכן שלו
# (8502) — שתיהן ניתנות לעקיפה בסביבה. אותם שמות משתנים בדיוק נקראים גם
# ב-server/app.py לכרטיסי אזור המנהל, כך שהכתובות לא יכולות להתפצל.
DASHBOARD_URL = os.getenv("ANNE_DASHBOARD_URL", "http://localhost:8501").rstrip("/")
ML_APP_URL = os.getenv("ANNE_ML_URL", "http://localhost:8502").rstrip("/")

# פקודת ההרצה של כל אפליקציה **מצמידה את הפורט שלה** — גם כאן וגם בכרטיסי
# אזור המנהל (server/app.py), מאותה סיבה: `streamlit run` בלי --server.port
# מדלג בשקט מ-8501 לפורט הפנוי הבא (8502), ואז עמוד החיזוי והדשבורד
# מתחלפים בכתובות. הפורט נגזר מהכתובת, כך שעקיפה בסביבה נשמרת בפקודה.
DASHBOARD_PORT = urlsplit(DASHBOARD_URL).port or 8501
ML_APP_PORT = urlsplit(ML_APP_URL).port or 8502
DASHBOARD_COMMAND = f"streamlit run dashboard/app.py --server.port {DASHBOARD_PORT}"
ML_APP_COMMAND = f"streamlit run dashboard/ml_app.py --server.port {ML_APP_PORT}"

# ── שני מקורות הנתונים ───────────────────────────────────────────────────
# התוויות של מתג מקור הנתונים (sidebar_data_source). זהות בשתי
# האפליקציות, כי המתג עצמו חי כאן ולא משוכפל בהן.
LIVE_SOURCE_HE = "נתונים חיים"
SYNTHETIC_SOURCE_HE = "נתונים סינתטיים"

# תקרת רוחב לתוויות ציר הקטגוריות, בפיקסלים. סופית בכוונה (לא 0) — ראה
# ההסבר ב-category_bar. 260px מכיל בנוחות את התווית הארוכה בפרויקט
# ("שתייה והחזרת נוזלים", ~19 תווים) בגופן 13px.
LABEL_LIMIT_PX = 260
# גובה שורה (עמודה אחת) בגרפי הקטגוריות.
ROW_HEIGHT_PX = 40


def inject_brand_css() -> None:
    """
    RTL + מיתוג אן בכל רכיבי העמוד (Streamlit הוא LTR ונטרלי כברירת מחדל).

    הצבעים כאן הם אותם טוקנים של assets/colors.css (חול/קורל/שזיף), כדי
    שהדשבורד, עמוד החיזוי, הצ'אט ואזור המנהל ייראו כמו אותה אפליקציה.
    """
    st.markdown(
        f"""
        <style>
          .stApp, section[data-testid="stSidebar"] {{ direction: rtl; }}
          h1, h2, h3, p, li, label, .stMarkdown {{ text-align: right; }}

          /* כותרות מקטע — קו מותג קצר מתחת לכל כותרת */
          .stApp h3 {{
            font-weight: 700;
            color: {INK};
            margin-bottom: 0.1rem;
          }}
          .stApp h3::after {{
            content: "";
            display: block;
            width: 44px;
            height: 3px;
            margin-top: 6px;
            background: {BRAND};
            border-radius: 999px;
          }}

          /* אריחי ה-KPI — כרטיסים לבנים רכים בגוני המותג */
          [data-testid="stMetric"] {{
            direction: rtl;
            text-align: right;
            background: #FFFFFF;
            border: 1px solid {GRID};
            border-radius: 16px;
            padding: 14px 16px;
            box-shadow: 0 4px 20px -2px rgba(110, 93, 115, 0.07);
          }}
          [data-testid="stMetricLabel"] {{ justify-content: flex-start; }}
          [data-testid="stMetricValue"] {{ color: {INK}; }}

          /* ── גרפים: פריסה LTR גם בעמוד RTL ──────────────────────────
             Vega מחשב את הפריסה שלו (ציר Y בצד שמאל של אזור הציור) בלי
             מושג על direction של העמוד. כשהמכל הוא RTL, SVG שרוחבו גדול
             מהמכל נגלש שמאלה ונחתך — וזה בדיוק הצד שבו יושבות תוויות
             הקטגוריות, כך שנשארת מהן אות אחת. אילוץ המכל ל-LTR מחזיר את
             הגלישה לצד הצפוי, ו-overflow: visible מונע חיתוך בכלל.
             הטקסט העברי עצמו נשאר RTL — כיווניות טקסט ב-SVG נקבעת לפי
             תוכן המקטע, לא לפי המכל. */
          [data-testid="stVegaLiteChart"],
          [data-testid="stVegaLiteChart"] > div,
          .vega-embed {{
            direction: ltr;
            overflow: visible !important;
          }}
          [data-testid="stVegaLiteChart"] svg {{ overflow: visible; }}

          /* ── סליידרים ומדי התקדמות: LTR מאולץ (באג מדווח) ───────────
             רכיבי הסליידר של Streamlit (BaseWeb) בונים את הפס מחלקי flex
             וממקמים את הידית לפי אחוז מהשמאל. בעמוד RTL הפריסה של החלקים
             מתהפכת בעוד מיקום הידית נשאר, ולכן "הנקודה שמזיזים" לא תואמת
             למד — נראה כאילו הסליידר הפוך. מד התקדמות (0→100%) מתמלא
             מהצד ההפוך מאותה סיבה. הרכיב מאולץ ל-LTR (ציר מספרי הוא
             ממילא LTR בכל שפה), והתווית העברית נשארת RTL ומיושרת לימין. */
          [data-testid="stSlider"],
          [data-testid="stProgress"] {{ direction: ltr; }}
          [data-testid="stSlider"] label,
          [data-testid="stProgress"] label {{
            direction: rtl;
            text-align: right;
            width: 100%;
          }}

          /* ── מתג מקור הנתונים (segmented control) ────────────────────
             שתי אפשרויות במתג אחד במקום רשימה נפתחת: המצב הנוכחי נראה
             במבט אחד וההחלפה היא לחיצה אחת, בלי לפתוח תפריט. הצביעה היא
             בטוקני המותג, כי ברירת המחדל של Streamlit אפורה ונטרלית —
             והמצב הפעיל בקורל *הכהה* (BRAND_STRONG), כי טקסט לבן על
             הקורל הבהיר אינו עומד ביחס ניגודיות של 4.5:1.
             שני הסלקטורים (testid + aria-checked) בכוונה: ב-Streamlit
             1.59 הכפתורים אינם נושאים data-testid ולכן *aria-checked* הוא
             שתופס בפועל (נמדד בדפדפן: הפעיל מקבל rgb(179,74,50) וטקסט
             לבן); סלקטור ה-testid נשאר כרשת ביטחון לגרסאות שכן מסמנות. */
          [data-testid="stButtonGroup"] {{ direction: rtl; width: 100%; }}
          [data-testid="stButtonGroup"] > div {{ width: 100%; }}
          [data-testid="stButtonGroup"] button {{
            flex: 1 1 0;
            border-radius: 999px !important;
            font-weight: 600;
            color: {INK};
          }}
          [data-testid="stBaseButton-segmented_controlActive"],
          [data-testid="stButtonGroup"] button[aria-checked="true"] {{
            background: {BRAND_STRONG} !important;
            border-color: {BRAND_STRONG} !important;
            color: #FFFFFF !important;
          }}

          /* כרטיס מודל בעמוד החיזוי */
          .model-card {{
            direction: rtl;
            text-align: right;
            padding: 14px 16px;
            margin-bottom: 10px;
            background: #FFFFFF;
            border: 1px solid {GRID};
            border-inline-start: 4px solid {BRAND};
            border-radius: 16px;
            box-shadow: 0 4px 20px -2px rgba(110, 93, 115, 0.07);
          }}
          .model-card h4 {{
            margin: 0 0 2px;
            font-size: 1.02rem;
            font-weight: 700;
            color: {INK};
          }}
          .model-card .model-family {{
            font-size: 0.78rem;
            color: {MUTED};
          }}
          .model-card p {{
            margin: 8px 0 0;
            font-size: 0.9rem;
            line-height: 1.7;
            color: {INK};
          }}

          /* הסבר מעל גרף — כרטיס שקט עם פס מותג בצד ההתחלה (ימין) */
          .chart-note {{
            direction: rtl;
            text-align: right;
            margin: 0.1rem 0 0.7rem;
            padding: 10px 14px;
            font-size: 0.86rem;
            line-height: 1.65;
            color: {MUTED};
            background: #FFFDFB;
            border: 1px solid {GRID};
            border-inline-start: 3px solid {BRAND};
            border-radius: 12px;
          }}

          /* כותרת ממותגת בראש העמוד */
          .brand-title {{
            margin: 0;
            font-size: 1.9rem;
            font-weight: 700;
            color: {INK};
          }}
          .brand-subtitle {{
            margin: 2px 0 0;
            font-size: 0.92rem;
            color: {MUTED};
          }}

          /* קישור בין שתי האפליקציות (סרגל הצד) */
          .sibling-app {{
            direction: rtl;
            text-align: right;
            margin: 0.2rem 0 0;
            font-size: 0.85rem;
            line-height: 1.7;
            color: {MUTED};
          }}
          .sibling-app code {{
            font-size: 0.78rem;
            direction: ltr;
            unicode-bidi: embed;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_setup(page_title: str) -> None:
    """אתחול עמוד אחיד לשתי האפליקציות: כותרת לשונית, אייקון, CSS ולוגו."""
    # אייקון הלשונית — הלוגו של אן; נפילה לאימוג'י אם הקובץ חסר/לא נתמך.
    try:
        st.set_page_config(
            page_title=page_title,
            page_icon=str(LOGO) if LOGO.exists() else "🩺",
            layout="wide",
        )
    except Exception:
        st.set_page_config(page_title=page_title, page_icon="🩺", layout="wide")
    inject_brand_css()
    # לוגו קבוע בראש סרגל הצד (וגם כשהוא מכונס) — מיתוג בכל מסך.
    if LOGO.exists():
        try:
            st.logo(str(LOGO), size="large", icon_image=str(LOGO))
        except Exception:
            pass


def chart_note(text: str) -> None:
    """
    הסבר קצר מעל גרף: מה סוג הגרף ומה הוא מודד — הסבר כללי וקבוע, לא
    פרשנות של הנתונים הנוכחיים (הנתונים משתנים עם כל סינון ועם כל שיחה
    חדשה, ומסקנה שנכתבה בקוד הייתה מתיישנת או פשוט שקרית).
    """
    st.markdown(f'<p class="chart-note">{text}</p>', unsafe_allow_html=True)


def brand_header(title: str, subtitle: str, logo_width: int = 76) -> None:
    """כותרת ממותגת: הלוגו של אן לצד הכותרת (RTL — הלוגו בצד ימין)."""
    logo_col, text_col = st.columns([1, 9], vertical_alignment="center")
    if LOGO.exists():
        logo_col.image(str(LOGO), width=logo_width)
    text_col.markdown(
        f'<h1 class="brand-title">{title}</h1>'
        f'<p class="brand-subtitle">{subtitle}</p>',
        unsafe_allow_html=True,
    )


def axis(**kwargs) -> alt.Axis:
    """ציר שקט: רשת עדינה בגוני חול, בלי קו-מסגרת ובלי שנתות."""
    return alt.Axis(
        gridColor=GRID, domain=False, ticks=False,
        labelColor=MUTED, titleColor=MUTED, **kwargs,
    )


def category_bar(
    frame: pd.DataFrame, value_col: str, value_title: str,
    colors: dict[str, str] | None = None, key_col: str = "label",
    color_key: str | None = None, value_format: str = ",",
) -> alt.Chart:
    """
    עמודות אופקיות לקטגוריות: הזהות בתוויות הציר + תווית ערך ישירה בקצה
    כל עמודה (ולכן אין צורך במקרא). צבע לפי מפתח הישות כשיש פלטה; אחרת
    גוון המותג האחיד.

    key_col הוא עמודת *התצוגה* (ברירת מחדל "label" — השם העברי). כל
    שכבת הנתונים מחזירה עמודת label לצד מפתח הישות, ובדיקת רגרסיה
    בסוללת האופליין מאמתת שזה נכון בכל אגרגציה ובכל מצב נתונים: קריאה
    עם frame שאין בו את עמודת המפתח היא בדיוק סוג הבאג שהפיל את העמוד
    כשמזהי האיורים הוחלפו בשמות עבריים.

    ההגנות מפני תוויות נחתכות (באג מדווח, שני סבבים) — כולן יחד, כי כל
    אחת מהן לבדה מכסה מנגנון אחר, ולאף אחת אין מחיר:
      * labelLimit *סופי ונדיב* (LABEL_LIMIT_PX). ברירת המחדל של
        Vega-Lite היא 180px והיא קיצרה תוויות ל-"…"; אבל דווקא 0 ("בלי
        תקרה") הוא מלכודת: בחלק ממסלולי חישוב הפריסה של Vega שטח
        התוויות נגזר מ-labelLimit עצמו, ואז 0 => שטח אפס, התווית נדחקת
        מחוץ ל-SVG ונראית ממנה אות אחת. ערך סופי גדול פותר את שני הצדדים.
      * גובה מפורש בפיקסלים ולא alt.Step: Streamlit מזריק
        autosize={"type":"fit"}, ו-Vega-Lite אינו תומך ב-fit כשהמידה
        נגזרת מ-step — שילוב שמוליד חישובי פריסה לא צפויים.
      * מרווח שמאלי מחושב מאורך התווית הארוכה: מקום פיזי שמור לתוויות,
        במקום להסתמך על ההקצאה האוטומטית של הציר.
      * מרווח בסוף הסקאלה (headroom) — תווית הערך יושבת אחרי קצה העמודה,
        ובלי המרווח היא נחתכת בגבול הגרף.
      * labelAngle=0 — תוויות אופקיות במפורש, לא מסובבות.
    (ובנוסף, ב-CSS: מכל הגרף מאולץ ל-LTR ול-overflow: visible, כדי
    שפריסת ה-RTL של העמוד לא תחתוך את עמודת התוויות — ראה inject_brand_css.)
    """
    if key_col not in frame.columns:
        # שגיאה מפורשת במקום KeyError עירום: זו טעות תכנות (קורא שהעביר
        # frame בלי עמודת התצוגה), והשם של העמודה החסרה הוא כל האבחנה.
        raise KeyError(
            f"category_bar: אין בטבלה עמודת תצוגה '{key_col}' "
            f"(עמודות קיימות: {list(frame.columns)})"
        )
    order = frame[key_col].tolist()
    values = pd.to_numeric(frame[value_col], errors="coerce").fillna(0.0)
    top = float(values.max()) if len(values) else 0.0
    headroom = top * 1.18 if top > 0 else 1.0
    # שמירת מקום פיזי לתוויות: אומדן שמרני של רוחב הטקסט בגופן 13px
    # (~7.5px לתו בעברית) + מרווח, בתוך גבולות שפויים.
    longest = max((len(str(label)) for label in order), default=0)
    label_gutter = min(max(int(longest * 7.5) + 24, 90), LABEL_LIMIT_PX)
    base = alt.Chart(frame).encode(
        y=alt.Y(f"{key_col}:N", sort=order, title=None,
                axis=axis(labelLimit=LABEL_LIMIT_PX, labelFontSize=13,
                          labelPadding=8, labelAngle=0)),
        x=alt.X(f"{value_col}:Q", title=value_title, axis=axis(),
                scale=alt.Scale(domain=[0, headroom], nice=False)),
        tooltip=[
            alt.Tooltip(f"{key_col}:N", title="קטגוריה"),
            alt.Tooltip(f"{value_col}:Q", title=value_title,
                        format=value_format),
        ],
    )
    if colors and color_key:
        domain = frame[color_key].tolist()
        color = alt.Color(
            f"{color_key}:N", legend=None,
            scale=alt.Scale(domain=domain,
                            range=[colors[k] for k in domain]),
        )
    else:
        color = alt.value(BRAND)
    bars = base.mark_bar(cornerRadiusEnd=4, height=24).encode(color=color)
    labels = base.mark_text(
        align="left", dx=6, fontSize=13, fontWeight="bold", color=INK,
    ).encode(text=alt.Text(f"{value_col}:Q", format=value_format))
    # גובה מפורש (ולא Step) — ראה ההסבר ב-docstring: Streamlit מזריק
    # autosize=fit, ו-fit אינו נתמך כשהמידה נגזרת מ-step.
    plot_height = max(len(order), 1) * ROW_HEIGHT_PX + 46
    return (bars + labels).properties(
        height=plot_height,
        padding={"left": label_gutter, "right": 24, "top": 6, "bottom": 6},
    )


@st.cache_data(ttl=60, show_spinner=False)
def load_turns_cached(db_path: str, mtime: float) -> pd.DataFrame:
    """טעינה עם cache; mtime של הקובץ הוא חלק מהמפתח — עדכון DB מרענן."""
    del mtime  # משמש רק כמפתח cache
    return load_turns_df(db_path)


def db_options() -> list[str]:
    """קובצי הלוג המוצעים: משתנה הסביבה (אם הוגדר) ואז anne_log*.db בשורש."""
    options: list[str] = []
    env_path = os.getenv(ENV_DB_VAR, "").strip()
    if env_path:
        options.append(env_path)
    for candidate in sorted(PROJECT_ROOT.glob("anne_log*.db")):
        if str(candidate) not in options:
            options.append(str(candidate))
    if not options:
        options.append(str(DEFAULT_DB_PATH))
    return options


def is_synthetic_db(path: str | Path) -> bool:
    """האם היעד הזה הוא הדאטה הסינתטי (לפי שמו — קובץ או טבלה)."""
    return "synthetic" in Path(path).name.lower()


def source_label(db_path: str | Path) -> str:
    """
    שם היעד לתצוגה: שם קובץ ה-SQLite, או "Supabase · <טבלה>".

    פונקציה אחת לשתי האפליקציות ולכל מקום שמציג "מאיפה הנתונים" (כיתוב
    התחתית, הודעת האיפוס, כיתוב האימון בעמוד החיזוי) — כדי שהחלפת
    backend לא תשאיר מסך אחד שמדבר על קבצים.
    """
    target = resolve_target(db_path)
    return f"Supabase · {target.table}" if target.is_supabase else target.label


def _probe_backend() -> str:
    """
    הכנת ה-backend הפעיל, והערה לתצוגה כשהוא אינו מה שהתבקש.

    ב-SQLite אין מה להכין (הקובץ נוצר בטעינה) ומוחזרת מחרוזת ריקה.
    ב-Supabase init_db הוא הכנה חד-פעמית בתהליך: חיבור + טבלה. כשהוא
    נכשל, שכבת ה-storage כבר החליפה ל-SQLite עם אזהרה בלוג — וכאן זה
    הופך גם להערה על המסך, כי דשבורד שמציג נתונים מקומיים בשקט בזמן
    שהמשתמש חושב שהוא מסתכל על הענן הוא בדיוק סוג התקלה שאי אפשר לאתר.

    התנאי נבדק מול ה-backend ש*התבקש* ולא מול זה שרץ בפועל: אחרי נפילה
    חיננית הפעיל הוא sqlite, ובדיקה מול הפעיל הייתה מעלימה את ההערה
    מהריצה השנייה של הסקריפט (Streamlit מריץ מחדש בכל אינטראקציה) —
    כלומר האזהרה הייתה מהבהבת פעם אחת ונעלמת.
    """
    from storage.backend import fallback_reason, requested_backend

    if requested_backend() != "supabase":
        return ""
    try:
        init_db()
    except Exception:  # לא אמור לקרות — init_db בולע ונופל חיננית
        pass
    reason = fallback_reason()
    if reason:
        return f"⚠ החיבור ל-Supabase נכשל — מוצגים נתונים מקומיים ({reason})."
    return ""


def db_choices() -> dict[str, str]:
    """
    שתי אפשרויות המתג: תווית -> היעד בפועל (קובץ SQLite או טבלה ב-Supabase).

    הבחירה היא בין שני *מצבים* ("חי" מול "סינתטי") ולא בין שמות קבצים,
    ולכן לכל מצב נבחר יעד אחד. ב-Supabase שני המצבים הם שתי טבלאות באותו
    פרויקט (turns / turns_synthetic) — המתג מחליף טבלה ולא חיבור, ולכן
    המעבר מיידי ואינו נוגע בהגדרות. ב-SQLite כל מצב הוא קובץ: הראשון
    מ-db_options שמתאים לו (משתנה הסביבה ANNE_LOG_DB נבדק ראשון ולכן הוא
    זה שגובר, בקטגוריה שלו), ואם אין כזה — נתיב ברירת המחדל של אותו מצב.
    הנתיב מוחזר גם כשהקובץ עדיין לא קיים: הוא נוצר ריק בקריאה הראשונה,
    וההודעה "אין עדיין רשומות" מוצגת כרגיל (empty_log_notice) במקום מסך
    שבור.
    """
    if resolve_target().is_supabase:
        return {LIVE_SOURCE_HE: LIVE_TABLE, SYNTHETIC_SOURCE_HE: SYNTHETIC_TABLE}
    options = db_options()
    live = next(
        (path for path in options if not is_synthetic_db(path)),
        str(DEFAULT_DB_PATH),
    )
    synthetic = next(
        (path for path in options if is_synthetic_db(path)),
        str(DEFAULT_SYNTH_DB),
    )
    return {LIVE_SOURCE_HE: live, SYNTHETIC_SOURCE_HE: synthetic}


def sidebar_data_source() -> str:
    """
    מתג מקור הנתונים + כפתור רענון (בסרגל הצד). מחזיר את הנתיב הנבחר.

    מתג של שתי אפשרויות ולא רשימה נפתחת: יש בדיוק שני מצבים, והמצב
    הפעיל צריך להיות גלוי בלי לפתוח תפריט. אותה פונקציה משרתת את שתי
    האפליקציות (זו שכבת התצוגה המשותפת), ולכן המתג יושב באותו מקום,
    באותו סטייל ועם אותן תוויות בשתיהן.

    required=True מונע ביטול בחירה (לחיצה על האפשרות הפעילה) — מצב שבו
    הרכיב מחזיר None ולא היה מקור נתונים כלל; ה-`or` שאחריו הוא חגורה
    נוספת, כדי שגם החזרת None לא תפיל את העמוד.
    """
    with st.sidebar:
        st.header("מקור נתונים")
        # בדיקת ה-backend *לפני* שמציירים את המתג: במצב Supabase זו הכנה
        # אחת לכל התהליך (חיבור + טבלה), ואם היא נכשלת שכבת ה-storage
        # נופלת חיננית ל-SQLite כאן ולא באמצע הטעינה — כך הכיתוב שמתחת
        # למתג מתאר את מה שבאמת נקרא, ולא את מה שהתבקש ב-.env.
        source_note = _probe_backend()
        choices = db_choices()
        # ברירת המחדל היא המצב של היעד הראשון — ANNE_LOG_DB אם הוגדר
        # (או ANNE_LOG_TABLE ב-Supabase), ואחרת הלוג החי. זו בדיוק
        # ההתנהגות שהייתה לרשימה הנפתחת (שהציגה את אותו קובץ ראשון).
        default_target = resolve_target()
        first_option = (default_target.table if default_target.is_supabase
                        else db_options()[0])
        default = (
            SYNTHETIC_SOURCE_HE if is_synthetic_db(first_option)
            else LIVE_SOURCE_HE
        )
        selected = st.segmented_control(
            "מקור הנתונים",
            list(choices),
            default=default,
            required=True,
            label_visibility="collapsed",
            width="stretch",
            key="anne_data_source",
            help="נתונים חיים = לוג השיחות האמיתי; נתונים סינתטיים = "
                 "דאטה שנוצר לניסוי (storage.synthetic).",
        )
        db_path = choices[selected or default]
        target = resolve_target(db_path)
        path = Path(db_path)
        if target.is_supabase:
            st.caption(f"Supabase (Postgres) · טבלה `{target.table}`")
        elif path.exists():
            st.caption(f"קובץ: `{path.name}`")
        elif is_synthetic_db(path):
            st.caption(
                f"`{path.name}` עדיין לא נוצר — "
                "`python -m storage.synthetic --rows 500`"
            )
        else:
            st.caption(
                f"`{path.name}` עדיין לא נוצר — הוא נכתב אוטומטית "
                "בשיחה הראשונה עם אן."
            )
        if source_note:
            st.caption(source_note)
        if st.button("↻ רענון נתונים", width="stretch"):
            st.cache_data.clear()
    return db_path


def load_selected(db_path: str) -> pd.DataFrame:
    """
    טעינת היעד הנבחר (עם ה-cache שמפתחו כולל את mtime הקובץ).

    ב-Supabase אין קובץ ולכן אין mtime: המפתח נשאר 0.0 והרענון נשען על
    ה-TTL של ה-cache (60 שניות) ועל כפתור הרענון — בדיוק כמו שהיה עם
    קובץ שנכתב מבחוץ בין שני רענונים.
    """
    path = Path(db_path)
    return load_turns_cached(db_path, path.stat().st_mtime if path.exists() else 0.0)


def sidebar_filters(df_all: pd.DataFrame) -> pd.DataFrame:
    """מסנני סרגל הצד (תאריך/תחום/מסלול/חירום) — מחזיר את הטבלה המסוננת."""
    with st.sidebar:
        st.header("מסננים")
        if df_all.empty:
            st.caption("אין נתונים לסינון.")
            return df_all
        min_date, max_date = df_all["date"].min(), df_all["date"].max()
        date_range = st.date_input(
            "טווח תאריכים", value=(min_date, max_date),
            min_value=min_date, max_value=max_date,
        )
        start_date, end_date = (
            date_range if isinstance(date_range, tuple) and len(date_range) == 2
            else (min_date, max_date)
        )
        topics = st.multiselect(
            "תחומים", list(TOPIC_ORDER), format_func=lambda t: TOPIC_HE[t],
        )
        paths = st.multiselect(
            "מסלול ייעוץ", list(PATH_ORDER), format_func=lambda p: PATH_HE[p],
        )
        emergency_only = st.checkbox("חירום בלבד")
    return filter_turns(
        df_all, start_date=start_date, end_date=end_date,
        topics=topics, paths=paths, emergency_only=emergency_only,
    )


def sidebar_sibling_link(title: str, url: str, command: str) -> None:
    """
    הפניה לאפליקציה האחות בסרגל הצד.

    שתי האפליקציות רצות בנפרד (שני פורטים), ולכן קישור בלבד אינו מספיק:
    אם השנייה אינה רצה, הקישור מוביל לשום מקום. לכן מוצגת גם פקודת
    ההרצה שלה — אותה פקודה שמופיעה בכרטיס באזור המנהל.
    """
    with st.sidebar:
        st.divider()
        st.markdown(
            f'<p class="sibling-app">↔ <a href="{url}" target="_blank">'
            f"{title}</a><br>אם אינה רצה: <code>{command}</code></p>",
            unsafe_allow_html=True,
        )


def sidebar_footer() -> None:
    """
    דמות אן וקרדיט היוצר בתחתית סרגל הצד.

    הקרדיט מגיע מ-credit.py — אותו מקור אמת של הצ'אט, אזור המנהל ועמודי
    המסמכים — ולכן די בשורה אחת כאן כדי ששתי אפליקציות ה-Streamlit
    יציגו בדיוק את אותו כיתוב (שתיהן קוראות ל-sidebar_footer).
    """
    with st.sidebar:
        st.divider()
        if LOGO_FIGURE.exists():
            st.image(str(LOGO_FIGURE), width="stretch")
        st.caption("אן — פרויקט לימודי. אינו מהווה ייעוץ רפואי.")
        st.markdown(credit_html(with_style=True), unsafe_allow_html=True)


def dataset_caption(db_path: str, filtered: pd.DataFrame,
                    df_all: pd.DataFrame) -> None:
    """שורת המקור בתחתית העמוד: איזה יעד, כמה נשאר אחרי סינון, גרסת סכמה."""
    st.caption(
        f"מקור: `{source_label(db_path)}` · {len(filtered):,} רשומות מסוננות "
        f"מתוך {len(df_all):,} · סכמה גרסה "
        f"{int(df_all['schema_version'].max())}"
    )


def empty_log_notice(db_empty: bool, filtered_empty: bool) -> bool:
    """
    הודעת "אין נתונים" אחידה. מחזיר True כשאין מה להציג (הקורא עוצר).

    מוחזר ערך במקום st.stop() כדי שהקורא יוכל להחליט — עמוד החיזוי, למשל,
    מציג את ההסבר הלימודי גם כשאין רשומות להצגה.
    """
    if db_empty:
        st.info(
            "אין עדיין רשומות בקובץ הנבחר. שיחות חדשות (python -m crew.main) "
            "נרשמות אוטומטית; לדאטה סינתטי לניסוי: "
            "`python -m storage.synthetic --rows 500`",
            icon="📭",
        )
        return True
    if filtered_empty:
        st.info("אין רשומות בטווח המסננים שנבחר.", icon="🔍")
        return True
    return False

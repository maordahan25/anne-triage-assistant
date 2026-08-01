"""
שכבת הנתונים של הדשבורד — pandas בלבד, בלי Streamlit.

כל הפונקציות טהורות (DataFrame -> DataFrame/dict) ומופרדות מהתצוגה בכוונה:
בדיקות האופליין מאמתות אותן ישירות על דאטה סינתטי, בלי להרים שרת. app.py
אחראי רק לתצוגה. הנתונים אנונימיים מהיסוד (ראה storage/turn_log.py) —
אין כאן שום טקסט משתמש, רק מונים, אורכים, משכים וקטגוריות סגורות.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from storage.turn_log import fetch_turns

# קטלוג האיורים (הרשימה הסגורה) — לתרגום מזהה לשם עברי בגרף האיורים.
# נקרא ישירות מה-JSON ולא דרך crew/, כדי שהדשבורד יישאר חופשי מתלות
# ב-crewai ובמפתח API.
ILLUSTRATIONS_JSON = (
    Path(__file__).resolve().parent.parent / "illustrations" / "illustrations.json"
)

# סדר קבוע לקטגוריות (הקצאת צבע לפי ישות — לעולם לא לפי מיקום/דירוג).
TOPIC_ORDER = ("wounds", "anxiety", "dehydration", "cold", "other")
TOPIC_HE = {
    "wounds": "פצעים וחתכים",
    "anxiety": "חרדה",
    "dehydration": "התייבשות",
    "cold": "הצטננות",
    "other": "אחר",
}

PATH_ORDER = ("direct", "crew", "none")
PATH_HE = {
    "direct": "ניתוב ישיר",
    "crew": "צוות היררכי",
    "none": "ללא ייעוץ",
}

# עמודות משכי השלבים (t_total מוצג כ-KPI נפרד, לא כשלב).
STAGE_ORDER = ("t_safety_gate", "t_triage", "t_consult", "t_compose")
STAGE_HE = {
    "t_safety_gate": "שער בטיחות",
    "t_triage": "אנמנזה (triage)",
    "t_consult": "ייעוץ מומחה",
    "t_compose": "ניסוח התשובה",
}

TOOL_ORDER = (
    "tool_rag_search", "tool_locate_place", "tool_get_weather",
    "tool_get_current_time", "tools_other",
)
TOOL_HE = {
    "tool_rag_search": "חיפוש RAG",
    "tool_locate_place": "איתור מיקום",
    "tool_get_weather": "מזג אוויר",
    "tool_get_current_time": "שעון",
    "tools_other": "אחר",
}


@lru_cache(maxsize=1)
def illustration_names() -> dict[str, str]:
    """
    מזהה איור -> שמו העברי, מתוך הרשימה הסגורה.

    קטלוג חסר/פגום אינו שובר את הדשבורד: מוחזר מילון ריק, והגרף יציג את
    המזהים כפי שהם (כפי שהיה קודם).
    """
    try:
        catalog = json.loads(ILLUSTRATIONS_JSON.read_text(encoding="utf-8"))
        return {
            key: str(record.get("name") or key)
            for key, record in (catalog.get("illustrations") or {}).items()
        }
    except Exception:
        return {}


def load_turns_df(db_path: str | Path | None = None) -> pd.DataFrame:
    """טעינת רשומות הלוג ל-DataFrame, עם עמודות זמן נגזרות (ts, date)."""
    rows = fetch_turns(db_path=db_path)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["date"] = df["ts"].dt.date
    return df


def filter_turns(
    df: pd.DataFrame,
    start_date=None,
    end_date=None,
    topics: list[str] | None = None,
    paths: list[str] | None = None,
    emergency_only: bool = False,
) -> pd.DataFrame:
    """סינון לפי טווח תאריכים, תחומים, מסלולי ייעוץ וחירום-בלבד."""
    if df.empty:
        return df
    mask = pd.Series(True, index=df.index)
    if start_date is not None:
        mask &= df["date"] >= start_date
    if end_date is not None:
        mask &= df["date"] <= end_date
    if topics:
        mask &= df["topic"].isin(topics)
    if paths:
        mask &= df["consult_path"].isin(paths)
    if emergency_only:
        mask &= df["emergency"] == 1
    return df[mask]


def _safe_float(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def compute_kpis(df: pd.DataFrame) -> dict:
    """מדדי הכותרת: היקף, חירום, ייעוץ, משך חציוני ועלות LLM ממוצעת."""
    if df.empty:
        return {
            "turns": 0, "sessions": 0, "emergencies": 0,
            "emergency_rate": 0.0, "consult_rate": 0.0,
            "t_total_median": None, "llm_calls_mean": None,
            "filtered_sources": 0,
        }
    turns = len(df)
    return {
        "turns": turns,
        "sessions": int(df["session_id"].nunique()),
        "emergencies": int(df["emergency"].sum()),
        "emergency_rate": float(df["emergency"].mean()),
        "consult_rate": float(df["consulted"].mean()),
        "t_total_median": _safe_float(df["t_total"].dropna().median()),
        "llm_calls_mean": _safe_float(df["llm_calls"].mean()),
        "filtered_sources": int(df["filtered_sources_count"].sum()),
    }


def daily_turns(df: pd.DataFrame) -> pd.DataFrame:
    """תורים וחירומים לפי יום — לגרף המגמה."""
    if df.empty:
        return pd.DataFrame(columns=["date", "turns", "emergencies"])
    grouped = (
        df.groupby("date")
        .agg(turns=("id", "count"), emergencies=("emergency", "sum"))
        .reset_index()
        .sort_values("date")
    )
    # datetime64 ולא datetime.date — סריאליזציה תקינה של הגרף בכל מנוע
    # (וגם ציר זמן רציף נכון ב-Vega-Lite).
    grouped["date"] = pd.to_datetime(grouped["date"])
    return grouped


def topic_counts(df: pd.DataFrame) -> pd.DataFrame:
    """פילוח תורי הייעוץ לפי תחום (רשומות ללא תחום אינן נספרות כאן)."""
    if df.empty:
        return pd.DataFrame(columns=["topic", "label", "turns"])
    counts = df["topic"].dropna().value_counts()
    rows = [
        {"topic": t, "label": TOPIC_HE[t], "turns": int(counts.get(t, 0))}
        for t in TOPIC_ORDER if counts.get(t, 0) > 0
    ]
    return pd.DataFrame(rows, columns=["topic", "label", "turns"])


def path_counts(df: pd.DataFrame) -> pd.DataFrame:
    """פילוח כל התורים לפי מסלול הייעוץ שנוסה (direct/crew/none)."""
    if df.empty:
        return pd.DataFrame(columns=["path", "label", "turns"])
    counts = df["consult_path"].value_counts()
    rows = [
        {"path": p, "label": PATH_HE[p], "turns": int(counts.get(p, 0))}
        for p in PATH_ORDER if counts.get(p, 0) > 0
    ]
    return pd.DataFrame(rows, columns=["path", "label", "turns"])


def stage_means(df: pd.DataFrame) -> pd.DataFrame:
    """משך ממוצע לכל שלב ב-pipeline (רק על תורים שבהם השלב רץ)."""
    rows = []
    for stage in STAGE_ORDER:
        if df.empty or stage not in df:
            continue
        values = df[stage].dropna()
        if len(values):
            rows.append({
                "stage": stage, "label": STAGE_HE[stage],
                "seconds": round(float(values.mean()), 2),
                "turns": int(len(values)),
            })
    return pd.DataFrame(rows, columns=["stage", "label", "seconds", "turns"])


def llm_calls_by_path(df: pd.DataFrame) -> pd.DataFrame:
    """ממוצע קריאות ה-LLM לתור לפי מסלול — עלות הניתוב הישיר מול ה-crew."""
    if df.empty:
        return pd.DataFrame(columns=["path", "label", "calls"])
    means = df.groupby("consult_path")["llm_calls"].mean()
    rows = [
        {"path": p, "label": PATH_HE[p], "calls": round(float(means[p]), 1)}
        for p in PATH_ORDER if p in means.index
    ]
    return pd.DataFrame(rows, columns=["path", "label", "calls"])


def tool_totals(df: pd.DataFrame) -> pd.DataFrame:
    """סך הפעלות כל כלי על פני התורים המסוננים."""
    rows = []
    for tool in TOOL_ORDER:
        total = 0 if df.empty or tool not in df else int(df[tool].sum())
        if total > 0:
            rows.append({"tool": tool, "label": TOOL_HE[tool], "uses": total})
    return pd.DataFrame(rows, columns=["tool", "label", "uses"])


def illustration_counts(df: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    """
    האיורים המודרכים הנפוצים ביותר (מזהי הרשימה הסגורה בלבד).

    עמודת label היא השם העברי מהקטלוג (לתצוגה); עמודת illustration נשארת
    המזהה עצמו — מפתח יציב לצבע/דיבוג, ולא תלוי בשינויי ניסוח.
    """
    if df.empty:
        return pd.DataFrame(columns=["illustration", "label", "turns"])
    counts = df["illustration_id"].dropna().value_counts().head(top_n)
    names = illustration_names()
    return pd.DataFrame({
        "illustration": counts.index,
        "label": [names.get(key, key) for key in counts.index],
        "turns": counts.values.astype(int),
    })


def session_turn_counts(df: pd.DataFrame) -> pd.DataFrame:
    """התפלגות אורך שיחה: כמה שיחות הכילו 1, 2, 3... תורים."""
    if df.empty:
        return pd.DataFrame(columns=["turns_in_session", "sessions"])
    lengths = df.groupby("session_id").size().value_counts().sort_index()
    return pd.DataFrame({
        "turns_in_session": lengths.index.astype(int),
        "sessions": lengths.values.astype(int),
    })

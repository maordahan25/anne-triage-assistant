"""
דשבורד הסקירה של "אן" — Streamlit מעל לוג השיחות האנונימי (storage/).

הרצה (מקצה הפרויקט, חינם וללא LLM):
    streamlit run dashboard/app.py --server.port 8501   # localhost:8501

זו אחת משתי אפליקציות ה-Streamlit של הפרויקט; השנייה היא עמוד מודל
החיזוי (dashboard/ml_app.py, פורט 8502). הן חולקות את שכבת הנתונים
(dashboard/data.py) ואת שכבת התצוגה (dashboard/ui.py) ורצות בנפרד.

עקרונות:
  * כל הנתונים אנונימיים מהיסוד (ראה storage/turn_log.py) — הדשבורד מציג
    מונים, אורכים, משכים וקטגוריות סגורות בלבד; אין בו טקסט משתמש כלל.
  * שכבת הנתונים (dashboard/data.py, pandas טהור) מופרדת מהתצוגה — נבדקת
    אופליין בלי שרת; הקובץ הזה אחראי רק ל-UI של הסקירה.
  * הצבעים, ה-CSS והגרפים מגיעים מ-dashboard/ui.py — מקור אחד לשתי
    האפליקציות, כדי שלא ייווצרו שתי פלטות ושני עיצובים.
  * כפתור המנהל (איפוס הלוג) קורא ל-storage.reset_log עם אישור כפול —
    מחיקת אמת (DELETE + VACUUM) של כל הרשומות, ובמצב Supabase של הטבלה
    בענן. לכן הוא יושב מאחורי שער קוד (dashboard/admin_access.py):
    האפליקציה נפרסת כאפליקציה ציבורית, וכששער הקוד סגור הכפתור אינו
    נוצר בעמוד כלל — ראה _admin_reset.
"""
from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# streamlit run מוסיף ל-sys.path את תיקיית הסקריפט (dashboard/), לא את שורש
# הפרויקט — מוסיפים אותו מפורשות כדי ש-storage/ ו-dashboard/ ייובאו כחבילות.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.data import (  # noqa: E402
    compute_kpis,
    daily_turns,
    illustration_counts,
    llm_calls_by_path,
    path_counts,
    session_turn_counts,
    stage_means,
    tool_totals,
    topic_counts,
)
from dashboard.ui import (  # noqa: E402
    BRAND,
    EMERGENCY,
    INK,
    LABEL_LIMIT_PX,
    ML_APP_COMMAND,
    ML_APP_URL,
    PATH_COLORS,
    TOPIC_COLORS,
    admin_gate,
    axis,
    brand_header,
    category_bar,
    chart_note,
    dataset_caption,
    empty_log_notice,
    load_selected,
    page_setup,
    sidebar_data_source,
    sidebar_filters,
    sidebar_footer,
    sidebar_sibling_link,
    source_label,
)
from storage.turn_log import reset_log  # noqa: E402


def _admin_reset(db_path: str) -> None:
    """
    אזור המנהל — איפוס הלוג, מאחורי שער הקוד (ui.admin_gate).

    הפעולה הזו מוחקת הכול (DELETE + VACUUM), ובמצב Supabase היא מוחקת את
    הטבלה **בענן**. האפליקציה נפרסת כאפליקציה ציבורית, ולכן כשהשער סגור
    לא נוצר כאן שום רכיב: לא הכפתור, לא תיבת האישור וגם לא ה-expander
    שעוטף אותם. פעולה מוחקת שקיימת בעמוד אך "מוסתרת" היא עדיין פעולה
    שקיימת בעמוד.

    כשהשער פתוח נשמרת ההגנה שהייתה כאן קודם: אישור מפורש בתיבת סימון,
    והכפתור נעול עד שהיא מסומנת.
    """
    gate = admin_gate("reset", "קוד מנהל — איפוס הלוג")
    if not gate.unlocked:
        return
    with st.expander("🗑️ אזור מנהל — איפוס הלוג", expanded=True):
        st.warning(
            "מחיקת **כל** הרשומות ממקור הנתונים הנבחר — פעולה סופית "
            "שאין ממנה חזרה.",
            icon="⚠️",
        )
        confirmed = st.checkbox("אני מבין/ה שהמחיקה סופית")
        if st.button(
            "מחיקת כל הרשומות", type="primary",
            disabled=not confirmed, width="stretch",
        ):
            deleted = reset_log(db_path=db_path)
            st.cache_data.clear()
            st.session_state["reset_message"] = (
                f"הלוג אופס: נמחקו {deleted} רשומות מ-"
                f"{source_label(db_path)}."
            )
            st.rerun()


def main() -> None:
    page_setup("אן — דשבורד לוג השיחות")

    # ── סרגל צד: מקור נתונים, מסננים ואזור מנהל ─────────────────────────
    db_path = sidebar_data_source()
    df_all = load_selected(db_path)
    filtered = sidebar_filters(df_all)

    with st.sidebar:
        st.divider()
        _admin_reset(db_path)

    sidebar_sibling_link(
        "מודל החיזוי (ML) — אפליקציה נפרדת", ML_APP_URL, ML_APP_COMMAND,
    )
    sidebar_footer()

    # ── גוף העמוד ────────────────────────────────────────────────────────
    brand_header(
        "דשבורד לוג השיחות",
        "ניתוח אנונימי של תורי השיחה עם אן — היקף, ניתוב, זמנים וכלים",
    )
    st.caption(
        "כל הנתונים אנונימיים מהיסוד: מונים, אורכים, משכים וקטגוריות "
        "סגורות בלבד — אין בלוג טקסט משתמש כלל (ראה storage/turn_log.py)."
    )
    if message := st.session_state.pop("reset_message", None):
        st.success(message, icon="🗑️")

    if empty_log_notice(df_all.empty, filtered.empty):
        st.stop()

    _render_overview(filtered)
    dataset_caption(db_path, filtered, df_all)


def _render_overview(filtered: pd.DataFrame) -> None:
    """גוף הסקירה: שורת ה-KPI, המגמה היומית, הפילוחים וטבלת הנתונים."""
    kpis = compute_kpis(filtered)

    # שורת ה-KPI — מספרי הכותרת שהדשבורד קיים בשבילם.
    st.subheader("מדדי מפתח")
    chart_note(
        "שורת המדדים מסכמת את כל התורים שעוברים את המסננים בסרגל הצד. "
        "\"תורי שיחה\" הוא מספר ההודעות שאן טיפלה בהן, ו\"שיחות\" הוא מספר "
        "השיחות הנפרדות שאליהן הן משתייכות (מזהה אנונימי פר-שיחה). "
        "המשך החציוני ומספר קריאות ה-LLM הם מדדי הביצועים והעלות של תור ממוצע."
    )
    tiles = st.columns(6)
    tiles[0].metric("תורי שיחה", f"{kpis['turns']:,}")
    tiles[1].metric("שיחות", f"{kpis['sessions']:,}")
    tiles[2].metric(
        "חירום", f"{kpis['emergencies']:,}",
        delta=f"{kpis['emergency_rate']:.1%} מהתורים",
        delta_color="off",
    )
    tiles[3].metric("שיעור ייעוץ", f"{kpis['consult_rate']:.0%}")
    tiles[4].metric(
        "משך תור (חציון)",
        "—" if kpis["t_total_median"] is None
        else f"{kpis['t_total_median']:.1f} שנ'",
    )
    tiles[5].metric(
        "קריאות LLM לתור",
        "—" if kpis["llm_calls_mean"] is None
        else f"{kpis['llm_calls_mean']:.1f}",
    )
    if kpis["filtered_sources"]:
        st.caption(
            f"🔎 נאמנות מקורות: {kpis['filtered_sources']} ציטוטי מקור "
            "נחסמו בסינון מול המאגר בתקופה המסוננת."
        )

    st.divider()

    # ── מגמה יומית ───────────────────────────────────────────────────────
    daily = daily_turns(filtered)
    st.subheader("תורים לאורך זמן")
    chart_note(
        "גרף שטח שמראה כמה תורי שיחה נרשמו בכל יום בטווח המסונן: ציר האופק "
        "הוא התאריך וציר האנך הוא מספר התורים באותו יום. כל נקודה אדומה "
        "מסמנת יום שבו שער הבטיחות פסק לפחות פסיקת חירום אחת. הגרף מיועד "
        "לזיהוי מגמה והיקף שימוש לאורך זמן, לא לניתוח תור בודד."
    )
    trend_base = alt.Chart(daily).encode(
        x=alt.X("date:T", title=None, axis=axis(format="%d/%m", grid=False)),
    )
    trend = trend_base.mark_area(
        line={"color": BRAND, "strokeWidth": 2},
        color=alt.Gradient(
            gradient="linear",
            stops=[alt.GradientStop(color="#FDEEE8", offset=0),
                   alt.GradientStop(color=BRAND, offset=1)],
            x1=1, x2=1, y1=1, y2=0,
        ),
        opacity=0.55,
    ).encode(
        y=alt.Y("turns:Q", title="תורים ביום", axis=axis()),
        tooltip=[
            alt.Tooltip("date:T", title="תאריך", format="%d/%m/%Y"),
            alt.Tooltip("turns:Q", title="תורים"),
            alt.Tooltip("emergencies:Q", title="חירומים"),
        ],
    )
    # נקודות חירום — צבע הבטיחות השמור, רק בימים שבהם היה חירום.
    emergencies = trend_base.transform_filter(
        alt.datum.emergencies > 0
    ).mark_point(
        color=EMERGENCY, filled=True, size=70, stroke="#FFFFFF", strokeWidth=1.5,
    ).encode(
        y=alt.Y("emergencies:Q"),
        tooltip=[
            alt.Tooltip("date:T", title="תאריך", format="%d/%m/%Y"),
            alt.Tooltip("emergencies:Q", title="חירומים"),
        ],
    )
    st.altair_chart(
        (trend + emergencies).properties(height=240), width="stretch",
    )
    st.caption("● נקודות אדומות — ימים עם פסיקת חירום של שער הבטיחות.")

    # ── פילוחים ──────────────────────────────────────────────────────────
    # כל גרף ברוחב מלא ובשורה נפרדת: התוויות בעברית (ובמיוחד שמות האיורים)
    # לא נכנסות בעמודה של חצי מסך, וזה מה שגרם לחיתוכן. ההסבר שמעל כל גרף
    # ממילא זקוק לרוחב שורה שלמה.
    st.divider()
    st.subheader("פילוח תחומים")
    chart_note(
        "עמודות אופקיות שמונות כמה תורי ייעוץ נרשמו בכל אחד מתחומי הידע של "
        "אן — פצעים וחתכים, חרדה, התייבשות והצטננות — ועוד \"אחר\" למקרים "
        "שמחוץ להם. התחום נקבע ע\"י הרופא המומחה בתום הייעוץ, ולא ע\"י "
        "המשתמש. תורים שלא הגיעו לייעוץ (ברכה, שאלת אנמנזה או פסיקת חירום) "
        "אינם נספרים כאן."
    )
    topics_df = topic_counts(filtered)
    if topics_df.empty:
        st.caption("אין תורי ייעוץ בטווח המסונן.")
    else:
        st.altair_chart(
            category_bar(topics_df, "turns", "תורים",
                         colors=TOPIC_COLORS, color_key="topic"),
            width="stretch",
        )

    st.subheader("מסלולי ייעוץ")
    chart_note(
        "כל תור מנותב באחד משלושה מסלולים: ניתוב ישיר אל הרופא המומחה של "
        "התחום, צוות היררכי שבו manager מנתב ומאציל, או ללא ייעוץ כלל. "
        "העמודות מונות תורים לפי המסלול שנוסה בפועל (ולא לפי הצלחתו). "
        "הניתוב הישיר הוא המהיר והחסכוני, וה-crew נכנס לתמונה כשהתחום לא זוהה."
    )
    paths_df = path_counts(filtered)
    if paths_df.empty:
        st.caption("אין תורים בטווח המסונן.")
    else:
        st.altair_chart(
            category_bar(paths_df, "turns", "תורים",
                         colors=PATH_COLORS, color_key="path"),
            width="stretch",
        )

    st.subheader("משך ממוצע לכל שלב")
    chart_note(
        "משך הריצה הממוצע, בשניות, של כל שלב בתור: שער הבטיחות, האנמנזה "
        "(triage), ייעוץ המומחה וניסוח התשובה. הממוצע מחושב רק על תורים "
        "שבהם השלב אכן רץ. שער הבטיחות והאנמנזה רצים במקביל, ולכן סכום "
        "השלבים גדול ממשך התור בפועל."
    )
    stages_df = stage_means(filtered)
    if stages_df.empty:
        st.caption("אין מדידות זמן בטווח המסונן.")
    else:
        st.altair_chart(
            category_bar(stages_df, "seconds", "שניות (ממוצע)",
                         value_format=".2f"),
            width="stretch",
        )

    st.subheader("קריאות LLM לתור לפי מסלול")
    chart_note(
        "מספר קריאות ה-LLM הממוצע לתור, בפילוח לפי מסלול הייעוץ. זהו מדד "
        "העלות הישיר של המערכת — כל קריאה היא בתשלום מול ספק המודל. "
        "ההשוואה בין המסלולים מראה את פער העלות בין ניתוב ישיר לבין הצוות "
        "ההיררכי, שבו נוספות קריאות הניתוב וההאצלה."
    )
    calls_df = llm_calls_by_path(filtered)
    if calls_df.empty:
        st.caption("אין קריאות LLM רשומות בטווח המסונן.")
    else:
        st.altair_chart(
            category_bar(calls_df, "calls", "קריאות (ממוצע)",
                         colors=PATH_COLORS, color_key="path",
                         value_format=".1f"),
            width="stretch",
        )

    st.subheader("שימוש בכלים")
    chart_note(
        "סך ההפעלות של כל כלי חיצוני בתורים המסוננים: חיפוש במאגר הידע "
        "(RAG), איתור מיקום, מזג אוויר ושעון. הכלים מופעלים גם דטרמיניסטית "
        "מתוך הקוד וגם ביוזמת הסוכנים, ושתי הדרכים נספרות יחד. אפס הפעלות "
        "לכלי מיקום/מזג אוויר הוא מצב תקין — הם נדרשים רק כשהוזכר יישוב."
    )
    tools_df = tool_totals(filtered)
    if tools_df.empty:
        st.caption("לא הופעלו כלים בטווח המסונן.")
    else:
        st.altair_chart(
            category_bar(tools_df, "uses", "הפעלות"),
            width="stretch",
        )

    st.subheader("איורים מודרכים נפוצים")
    chart_note(
        "האיורים מהרשימה הסגורה שצורפו לתשובות בתדירות הגבוהה ביותר (עד "
        "שמונה המובילים). איור נבחר ע\"י הרופא המומחה מתוך קטגוריית התחום "
        "שלו, או בהתאמה דטרמיניסטית בקוד כשהרופא לא בחר. השמות הם שמות "
        "האיורים מקטלוג illustrations/, ולא מזהי הקבצים."
    )
    ill_df = illustration_counts(filtered)
    if ill_df.empty:
        st.caption("לא צורפו איורים בטווח המסונן.")
    else:
        st.altair_chart(
            category_bar(ill_df, "turns", "תורים"),
            width="stretch",
        )

    st.subheader("אורך שיחה (תורים לשיחה)")
    chart_note(
        "היסטוגרמה של אורכי השיחות: לכל מספר תורים (1, 2, 3 …) — כמה שיחות "
        "נמשכו בדיוק כך. שיחה היא רצף התורים שנרשמו תחת אותו מזהה שיחה "
        "אנונימי. עמודה גבוהה ב-1 מעידה על פניות חד-פעמיות, וזנב ימני על "
        "שיחות מרובות-תורים שבהן אן תשאלה והמשיכה."
    )
    lengths_df = session_turn_counts(filtered)
    # מרווח בראש הסקאלה — תווית הערך יושבת מעל העמודה ובלעדיו הייתה נחתכת.
    sessions_top = float(lengths_df["sessions"].max()) if len(lengths_df) else 1.0
    length_base = alt.Chart(lengths_df).encode(
        x=alt.X("turns_in_session:O", title="תורים בשיחה",
                axis=axis(labelLimit=LABEL_LIMIT_PX, labelFontSize=13,
                          labelAngle=0)),
        y=alt.Y("sessions:Q", title="שיחות", axis=axis(),
                scale=alt.Scale(domain=[0, sessions_top * 1.15], nice=False)),
        tooltip=[
            alt.Tooltip("turns_in_session:O", title="תורים בשיחה"),
            alt.Tooltip("sessions:Q", title="שיחות"),
        ],
    )
    st.altair_chart(
        (length_base.mark_bar(cornerRadiusEnd=4, color=BRAND)
         + length_base.mark_text(dy=-8, color=INK).encode(text="sessions:Q")
         ).properties(height=220),
        width="stretch",
    )

    # תצוגת טבלה מלאה (נגישות: לכל הגרפים יש מקבילה טבלאית) + ייצוא CSV.
    with st.expander("📋 טבלת הנתונים המלאה (מסוננת)"):
        table = filtered.drop(columns=["ts"], errors="ignore")
        st.dataframe(table, width="stretch", hide_index=True)
        st.download_button(
            "הורדת CSV (נתונים אנונימיים)",
            table.to_csv(index=False).encode("utf-8-sig"),
            file_name="anne_log_export.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()

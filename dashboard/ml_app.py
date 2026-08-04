"""
עמוד מודל החיזוי של "אן" — אפליקציית Streamlit נפרדת מעל אותו לוג שיחות.

הרצה (מקצה הפרויקט, חינם וללא LLM):
    streamlit run dashboard/ml_app.py --server.port 8502

**הדגמת יכולת ML לימודית בלבד — לא כלי קליני.** המודלים מאומנים על דאטה
סינתטי ועל מדגם קטן מאוד של מקרי חירום; ההסתברויות כאן אינן הערכה רפואית.

זו אחת משתי אפליקציות ה-Streamlit של הפרויקט; השנייה היא דשבורד הסקירה
(dashboard/app.py, פורט 8501). שתיהן חולקות את שכבת הנתונים
(dashboard/data.py) ואת שכבת התצוגה (dashboard/ui.py) — פלטה, CSS, כותרת
ממותגת, גרף הקטגוריות, בורר קובץ הלוג והמסננים — ורצות בנפרד.

מבנה העמוד (סדר לימודי מכוון): מה מנסים לחזות -> אימון -> כרטיס לכל מודל
(הסבר נגיש + מדדים + המתמטיקה) -> השוואה + מילון מדדים -> בחירת מודל ->
על מה הוא מסתכל -> חיזוי אינטראקטיבי בכל המודלים -> המודל מול המציאות ->
הערת יושרה על מלכודת דליפה עקיפה.

התלות ב-scikit-learn רכה: בלי המודול העמוד עולה ומסביר מה להתקין.
"""
from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# streamlit run מוסיף ל-sys.path את תיקיית הסקריפט (dashboard/), לא את שורש
# הפרויקט — מוסיפים אותו מפורשות כדי ש-ml/, storage/ ו-dashboard/ ייובאו.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.data import TOPIC_HE, TOPIC_ORDER  # noqa: E402
from dashboard.ui import (  # noqa: E402
    DASHBOARD_COMMAND,
    DASHBOARD_URL,
    EMERGENCY,
    LABEL_LIMIT_PX,
    MODEL_COLORS,
    MUTED,
    admin_gate,
    axis,
    brand_header,
    category_bar,
    chart_note,
    dataset_caption,
    load_selected,
    page_setup,
    sidebar_data_source,
    sidebar_filters,
    sidebar_footer,
    sidebar_sibling_link,
    source_label,
)

# מודול החיזוי — תלות רכה: העמוד עולה גם אם scikit-learn/joblib חסרים
# (תוצג הודעת תלויות במקום מסך שבור).
try:
    from ml.models import (  # noqa: E402
        DEFAULT_MODEL_KEY,
        METRIC_GLOSSARY_HE,
        MODEL_SPECS,
    )
    from ml.predict import (  # noqa: E402
        available_models,
        load_model,
        predict_er_probability,
        predict_frame,
    )
    from ml.train import (  # noqa: E402
        resolve_model_path,
        save_all_models,
        train_all_models,
    )
    ML_AVAILABLE = True
except Exception:  # pragma: no cover - סביבה בלי sklearn
    ML_AVAILABLE = False


@st.cache_resource(show_spinner=False)
def _load_bundle(model_path: str, mtime: float):
    """
    טעינת bundle המודלים עם cache (cache_resource — אובייקט כבד, לא נתונים).

    בלי ה-cache כל הזזת סליידר בעמוד הייתה טוענת ~0.6MB מהדיסק מחדש
    (נמדד ~140ms) — מורגש בדיוק בחלק האינטראקטיבי. ה-mtime הוא חלק
    מהמפתח, כך שאימון מחדש נטען אוטומטית.
    """
    del mtime  # משמש רק כמפתח cache
    return load_model(model_path)


def main() -> None:
    page_setup("אן — מודל חיזוי (ML)")

    db_path = sidebar_data_source()
    df_all = load_selected(db_path)
    filtered = sidebar_filters(df_all)
    sidebar_sibling_link(
        "דשבורד הסקירה — אפליקציה נפרדת", DASHBOARD_URL, DASHBOARD_COMMAND,
    )
    sidebar_footer()

    _page_header()
    if not ML_AVAILABLE:
        st.info(
            "תלויות מודול החיזוי (scikit-learn/joblib) אינן מותקנות — "
            "התקינו עם: `pip install --prefer-binary -r llm_requirements.txt`",
            icon="📦",
        )
        return

    if df_all.empty:
        st.info(
            "אין עדיין רשומות בקובץ הנבחר — אי אפשר לאמן ואין מה להציג על "
            "נתונים. לדאטה סינתטי לניסוי: "
            "`python -m storage.synthetic --rows 500`",
            icon="📭",
        )

    _render_prediction(filtered, db_path)

    if not df_all.empty:
        dataset_caption(db_path, filtered, df_all)


def _page_header() -> None:
    """כותרת ממותגת לעמוד החיזוי (לוגו אן + כותרת + אזהרת ההדגמה)."""
    brand_header(
        "מודל חיזוי — הסתברות להפניה למיון",
        "הדגמה לימודית של Machine Learning מעל לוג השיחות האנונימי של אן",
        logo_width=62,
    )
    st.warning(
        "**הדגמת יכולת ML לימודית בלבד — לא כלי קליני.** המודלים מאומנים על "
        "דאטה סינתטי ועל מדגם קטן מאוד של מקרי חירום; ההסתברויות כאן אינן "
        "הערכה רפואית ואינן מתאימות לשום שימוש קליני.",
        icon="⚠️",
    )


def _render_model_card(spec, metrics: dict) -> None:
    """כרטיס מודל אחד: שם, משפחה, הסבר נגיש, מדדים, והמתמטיקה שמאחוריו."""
    st.markdown(
        f'<div class="model-card">'
        f'<h4>{spec.name_he}</h4>'
        f'<div class="model-family">{spec.family_he} · {spec.summary_he}</div>'
        f'<p>{spec.explanation_he}</p>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if metrics:
        tiles = st.columns(4)
        tiles[0].metric("ROC-AUC", f"{metrics.get('roc_auc', 0):.3f}")
        tiles[1].metric("Average Precision",
                        f"{metrics.get('average_precision', 0):.3f}")
        tiles[2].metric("Recall", f"{metrics.get('recall', 0):.0%}")
        tiles[3].metric("Precision", f"{metrics.get('precision', 0):.0%}")
    with st.expander(f"🧮 המתמטיקה של {spec.name_he}"):
        st.caption(spec.math_intro_he)
        for formula, note in zip(spec.formulas, spec.math_notes_he):
            st.latex(formula)
            st.caption(note)
        # נוסחה בלי הערה מקבילה (אם המפרט אינו מאוזן) — עדיין מוצגת.
        for formula in spec.formulas[len(spec.math_notes_he):]:
            st.latex(formula)


def _contribution_chart(entry: dict, spec) -> None:
    """גרף הפרשנות: יחסי סיכויים (מודל לינארי) או חשיבות תכונה (עצים)."""
    contributions = entry.get("contributions")
    if not contributions or not contributions.get("values"):
        st.caption(f"אין מה לפרש עבור {spec.name_he} — {spec.interpretation_he}")
        return
    kind = contributions["kind"]
    values = contributions["values"]
    if kind == "odds_ratio":
        # מרחק מ-1 הוא עוצמת ההשפעה (1 = חסר השפעה).
        ordered = sorted(values.items(), key=lambda kv: -abs(kv[1] - 1))
        title, fmt = "יחס סיכויים (1 = חסר השפעה)", ".2f"
    else:
        ordered = sorted(values.items(), key=lambda kv: -kv[1])
        title, fmt = "חשיבות התכונה", ".3f"
    frame = pd.DataFrame(
        [{"label": name, "value": round(value, 4)}
         for name, value in ordered[:8]],
    )
    chart_note(
        f"{spec.interpretation_he} הגרף מציג את התכונות *כפי שהמודל ראה "
        "אותן* — כלומר אחרי הקידוד, כך שכל תחום הוא תכונה בינארית בפני "
        "עצמה. הסדר הוא לפי עוצמת ההשפעה, ולא לפי חשיבות רפואית."
    )
    st.altair_chart(
        category_bar(frame, "value", title, value_format=fmt),
        width="stretch",
    )


def _render_prediction(filtered: pd.DataFrame, db_path: str) -> None:
    """
    גוף עמוד החיזוי — הדגמת ML לימודית מעל הלוג.

    מתפקד בכל מצב: בלי מודל מאומן (הנחיה + כפתור אימון), עם bundle ישן של
    מודל בודד, עם bundle מלא, וגם כשאין רשומות בלוג הנבחר.
    """
    # ── מה בכלל מנסים לחזות ─────────────────────────────────────────────
    st.subheader("מה המודל מנסה לחזות")
    chart_note(
        "המשימה: לקבל את מה שידוע ברגע שהמשתמש שלח הודעה — התחום המשוער, "
        "מספר התור בשיחה, אורך ההודעה והשעה — ולהחזיר מספר אחד בין 0 ל-1: "
        "ההסתברות שהתור הזה יסתיים בהפניה למיון (כלומר שדקסטר, שער הבטיחות, "
        "יפסוק חירום). זו בעיית *סיווג בינארי*: היעד הוא כן/לא, והמודל "
        "מחזיר הסתברות ולא החלטה. מה שהמודל לומד הוא דפוסים סטטיסטיים "
        "בנתונים הסינתטיים — לא ידע רפואי."
    )
    facts = st.columns(3)
    facts[0].metric("תכונות (features)", "4")
    facts[1].metric("יעד (target)", "emergency")
    facts[2].metric("סוג המשימה", "סיווג בינארי")
    st.caption(
        "התכונות נבחרו כך שכולן ידועות *בתחילת* התור. כל מה שנקבע אחרי "
        "פסיקת החירום (דגלים אדומים, מסלול הייעוץ, תזמונים, מוני כלים) "
        "מוחרג במפורש ב-ml/dataset.py — אחרת המודל היה \"מנבא\" את התשובה "
        "מתוך התשובה (target leakage)."
    )

    # ── אימון (מחדש) על קובץ הלוג הנבחר — מאחורי שער הקוד ────────────────
    # אימון הוא פעולה שכותבת (bundle חדש ל-ml/models/) וגם חישוב כבד, ולכן
    # היא כפופה לאותו שער כמו איפוס הלוג: האפליקציה ציבורית, וכפתור שמאמן
    # מודל בלחיצה אחת הוא גם כתיבה וגם עומס שמבקר אנונימי יכול להפעיל שוב
    # ושוב. שער סגור -> הכפתור וה-expander אינם נוצרים כלל.
    gate = admin_gate("train", "קוד מנהל — אימון מודלים")
    if gate.unlocked:
        with st.expander("🎓 אימון כל המודלים על הקובץ הנבחר"):
            st.caption(
                f"אימון על `{source_label(db_path)}` ושמירה אל "
                f"`{resolve_model_path().name}`. כל המודלים מאומנים על "
                "*אותו* פיצול אימון/בדיקה — אחרת ההשוואה ביניהם חסרת "
                "משמעות. אם בקובץ אין גם תורי חירום וגם תורי שגרה — "
                "האימון ייעצר בהודעה ברורה."
            )
            if st.button("אימון ושמירה", width="stretch"):
                try:
                    results = train_all_models(db_path)
                    save_all_models(results)
                    _load_bundle.clear()  # המודל החדש ייטען במקום שב-cache
                    trained = ", ".join(
                        f"{entry['metrics']['model_name_he']} "
                        f"({entry['metrics']['roc_auc']})"
                        for entry in results.values()
                    )
                    st.success(
                        f"אומנו ונשמרו {len(results)} מודלים — {trained}"
                    )
                except ValueError as exc:
                    st.error(str(exc))

    model_file = resolve_model_path()
    try:
        bundle = _load_bundle(
            str(model_file),
            model_file.stat().st_mtime if model_file.exists() else 0.0,
        )
    except FileNotFoundError:
        # ההודעה חייבת להתאים למה שיש על המסך: כששער הקוד סגור אין "כפתור
        # למעלה", והפניה אליו הייתה שולחת את הקורא לחפש רכיב שלא קיים.
        st.info(
            "אין עדיין מודל מאומן — אמנו בכפתור למעלה, או בשורת הפקודה: "
            "`python -m ml.train`"
            if gate.unlocked else
            "אין עדיין מודל מאומן. האימון נעשה בשורת הפקודה: "
            "`python -m ml.train`",
            icon="🎓",
        )
        return
    except ValueError as exc:
        st.error(str(exc))
        return

    models = available_models(bundle)
    known = [model for model in models if model["key"] in MODEL_SPECS]
    reference = models[0]["metrics"] if models else {}
    st.caption(
        f"אומן על {reference.get('rows', 0):,} רשומות "
        f"({reference.get('positives', 0)} תורי חירום) · מדגם הערכה "
        f"{reference.get('test_rows', 0)} רשומות "
        f"({reference.get('test_positives', 0)} חירום) · scikit-learn "
        f"{bundle.get('sklearn_version', '—')}"
    )

    st.divider()

    # ── אילו מודלים אומנו ───────────────────────────────────────────────
    st.subheader(f"המודלים שאומנו ({len(known)})")
    chart_note(
        "כל המודלים כאן פותרים בדיוק את אותה משימה ומאומנים על אותם "
        "נתונים ואותו פיצול — מה שמתחלף הוא *השיטה*. לכל מודל: הסבר במילים "
        "פשוטות, המדדים שלו על המדגם המוחזק, והמתמטיקה שמאחוריו בלשונית "
        "נפרדת. הסדר אינו דירוג איכות."
    )
    for model in known:
        _render_model_card(MODEL_SPECS[model["key"]], model["metrics"])

    # ── השוואה + מילון מדדים ────────────────────────────────────────────
    st.subheader("השוואת המודלים")
    chart_note(
        "עמודות אופקיות של ROC-AUC לכל מודל, על אותו מדגם מוחזק. ROC-AUC "
        "מודד *דירוג*: ההסתברות שהמודל ייתן ציון גבוה יותר למקרה חירום "
        "מאשר למקרה שגרה. הקו התחתון הוא מודל הבסיס (0.5, כמו הטלת מטבע) "
        "— כל מודל שאינו מעליו לא לומד שום דבר שימושי."
    )
    if known:
        comparison = pd.DataFrame([
            {
                "key": model["key"],
                "label": model["name_he"],
                "roc_auc": model["metrics"].get("roc_auc", 0.0),
            }
            for model in known
        ])
        st.altair_chart(
            category_bar(comparison, "roc_auc", "ROC-AUC",
                         colors=MODEL_COLORS, color_key="key",
                         value_format=".3f"),
            width="stretch",
        )
        table = pd.DataFrame([
            {
                "מודל": model["name_he"],
                "ROC-AUC": model["metrics"].get("roc_auc"),
                "Average Precision": model["metrics"].get("average_precision"),
                "Brier (נמוך=טוב)": model["metrics"].get("brier"),
                "Recall": model["metrics"].get("recall"),
                "Precision": model["metrics"].get("precision"),
                "תפס (TP)": model["metrics"].get("confusion", {}).get("tp"),
                "אזעקות שווא (FP)": model["metrics"].get("confusion", {}).get("fp"),
                "פספס (FN)": model["metrics"].get("confusion", {}).get("fn"),
            }
            for model in known
        ])
        st.dataframe(table, width="stretch", hide_index=True)

    with st.expander("📖 מילון המדדים — מה כל מספר בטבלה אומר"):
        for name, meaning in METRIC_GLOSSARY_HE:
            st.markdown(f"**{name}** — {meaning}")
        st.caption(
            "שימו לב שאין כאן \"דיוק\" (accuracy) בכלל: כשחירום הוא כ-4% "
            "מהתורים, מודל שמנחש \"לא\" לכולם מגיע ל-96% דיוק ואינו שווה "
            "כלום. זו הסיבה שמודדים דירוג (ROC-AUC), כיסוי (Recall) וכיול "
            "(Brier) במקום."
        )

    st.divider()

    # ── בחירת מודל להמשך העמוד ──────────────────────────────────────────
    model_keys = [model["key"] for model in known] or [DEFAULT_MODEL_KEY]
    names = {model["key"]: model["name_he"] for model in known}
    selected_key = st.selectbox(
        "מודל לתצוגה בהמשך העמוד",
        model_keys,
        format_func=lambda key: names.get(key, key),
        help="בוחר את המודל לגרף הפרשנות ולפיזור על הנתונים המסוננים.",
    )
    selected = next(
        (model for model in known if model["key"] == selected_key),
        None,
    )
    selected_spec = MODEL_SPECS.get(selected_key)

    # ── מה המודל מסתכל עליו ─────────────────────────────────────────────
    if selected and selected_spec:
        st.subheader(f"על מה {selected_spec.name_he} מסתכל")
        _contribution_chart(selected, selected_spec)

    st.divider()

    # ── חיזוי אינטראקטיבי ───────────────────────────────────────────────
    st.subheader("חיזוי אינטראקטיבי (מה-אם)")
    chart_note(
        "ארבעת הבקרים הם *בדיוק* המשתנים שהמודלים מקבלים: תחום, מספר התור "
        "בשיחה, אורך ההודעה והשעה — כולם ידועים בתחילת התור. כל שינוי מריץ "
        "חיזוי מחדש בכל המודלים במקביל, כך שאפשר לראות איך אותו מקרה בדיוק "
        "נראה בעיני שיטות שונות. זו הדגמה לימודית, לא הערכה רפואית."
    )
    widgets = st.columns(4)
    topic = widgets[0].selectbox(
        "תחום", [*TOPIC_ORDER, "unknown"],
        format_func=lambda t: TOPIC_HE.get(t, "לא זוהה תחום"),
    )
    turn_index = widgets[1].number_input("מס' תור בשיחה", 1, 20, 1)
    # סליידרים: הרכיב מאולץ ל-LTR ב-CSS (ראה ui.inject_brand_css) כדי
    # שהידית תתאים למד; הערך הנבחר מוצג גם במפורש מתחת, כדי שלא יישאר
    # שום ספק מה נכנס לחיזוי.
    message_chars = widgets[2].slider(
        "אורך ההודעה (תווים)", min_value=0, max_value=400, value=60, step=5,
        help="0 = הודעה ריקה; 400 = הודעה ארוכה מאוד.",
    )
    hour = widgets[3].slider(
        "שעה ביום", min_value=0, max_value=23, value=12, step=1,
        format="%d:00", help="0 = חצות; 23 = 23:00.",
    )
    st.caption(
        f"החיזוי מחושב עבור: תחום = **{TOPIC_HE.get(topic, 'לא זוהה תחום')}** · "
        f"תור מספר **{int(turn_index)}** בשיחה · הודעה באורך "
        f"**{int(message_chars)}** תווים · שעה **{int(hour):02d}:00**."
    )

    record = {
        "topic": topic, "turn_index": int(turn_index),
        "user_message_chars": int(message_chars),
        "ts_utc": f"2026-01-01T{int(hour):02d}:00:00Z",
    }
    predictions = []
    for model in known or [{"key": None, "name_he": "המודל"}]:
        try:
            probability = predict_er_probability(
                record, bundle=bundle, model_key=model["key"],
            )
        except Exception:
            continue
        predictions.append({
            "key": model["key"] or DEFAULT_MODEL_KEY,
            "label": model["name_he"],
            "probability": round(probability, 4),
        })

    if predictions:
        cards = st.columns(len(predictions))
        for column, prediction in zip(cards, predictions):
            column.metric(prediction["label"], f"{prediction['probability']:.1%}")
        st.altair_chart(
            category_bar(
                pd.DataFrame(predictions), "probability",
                "הסתברות חזויה להפניה למיון", colors=MODEL_COLORS,
                color_key="key", value_format=".1%",
            ),
            width="stretch",
        )
    st.caption(
        "הערת כיול: איזון המחלקות (class_weight='balanced' / sample_weight — "
        "חירום נדיר) מנפח את ההסתברויות המוחלטות, ולכן שני מודלים יכולים "
        "לדרג מקרים באותו סדר ובכל זאת להציג אחוזים שונים מאוד. הסדר היחסי "
        "הוא המשמעותי, לא הערך המוחלט. מודל הבסיס מחזיר תמיד את אותו מספר — "
        "זה לא באג, זו כל הפואנטה שלו."
    )

    st.divider()

    # ── המודל מול המציאות ───────────────────────────────────────────────
    st.subheader("המודל על הנתונים המסוננים")
    chart_note(
        "פיזור (strip plot) של ההסתברות שהמודל הנבחר חוזה לכל אחד מהתורים "
        "המסוננים, מפוצל לשתי שורות לפי מה שקרה בפועל: שגרה מול חירום. כל "
        "קו אנכי הוא תור אחד, וציר האופק הוא ההסתברות החזויה. הגרף ממחיש "
        "עד כמה המודל מפריד בין הקבוצות — הוא אינו כלי החלטה."
    )
    if filtered.empty:
        st.caption(
            "אין רשומות בטווח המסננים שנבחר — הגרף הזה מצייר תורים אמיתיים "
            "מהלוג, ולכן הוא ריק. שנו את המסננים בסרגל הצד או בחרו קובץ לוג אחר."
        )
    else:
        scored = pd.DataFrame({
            "probability": predict_frame(
                filtered, bundle=bundle, model_key=selected_key,
            ),
            "actual": filtered["emergency"].map(
                {0: "שגרה", 1: "חירום בפועל"}
            ).to_numpy(),
        })
        strip = alt.Chart(scored).mark_tick(
            thickness=2, size=18, opacity=0.55,
        ).encode(
            x=alt.X("probability:Q", title="הסתברות חזויה להפניה למיון",
                    scale=alt.Scale(domain=[0, 1]), axis=axis(format="%")),
            y=alt.Y("actual:N", title=None, sort=["שגרה", "חירום בפועל"],
                    axis=axis(labelFontSize=13, labelLimit=LABEL_LIMIT_PX,
                              labelAngle=0)),
            color=alt.Color(
                "actual:N", legend=None,
                scale=alt.Scale(domain=["שגרה", "חירום בפועל"],
                                range=[MUTED, EMERGENCY]),
            ),
            tooltip=[alt.Tooltip("probability:Q", title="הסתברות",
                                 format=".1%")],
        ).properties(height=170, padding={"left": 90, "right": 24,
                                          "top": 6, "bottom": 6})
        st.altair_chart(strip, width="stretch")
        st.caption(
            f"כל קו — תור אחד ({len(scored):,} תורים מסוננים), לפי "
            f"{names.get(selected_key, selected_key)}. המודל מפריד היטב כשקווי "
            "החירום (אדום) מרוכזים בצד ההסתברות הגבוהה, הרחק מקווי השגרה."
        )

    # ── הערת יושרה לימודית: מלכודת שכדאי להכיר ─────────────────────────
    with st.expander("⚠️ מלכודת שכדאי להכיר: למה \"ללא תחום\" כל כך חזק"):
        st.markdown(
            "בגרף הפרשנות התכונה **\"תחום: ללא תחום\"** יוצאת בדרך כלל "
            "החזקה ביותר — ולא בגלל תובנה רפואית. הסיבה מבנית: כשדקסטר "
            "פוסק חירום, התור נעצר *לפני* הייעוץ, ולכן לא נקבע לו תחום "
            "בכלל. המודל לומד את הקשר הזה ומגלה \"אין תחום ⇒ חירום\" — "
            "כלומר הוא לומד את **תוצאת** התור ולא את **סיבתו**.\n\n"
            "זו דוגמה חיה ל-*דליפה עקיפה* (proxy leakage): התכונה עוברת "
            "את הכלל הפורמלי (\"ידועה בתחילת התור\") אבל בפועל היא מושפעת "
            "מההכרעה. במערכת אמיתית היו כאן שתי אפשרויות: להוציא את התחום "
            "מהתכונות, או להשתמש ברמז התחום של אן מרגע התשאול (לפני "
            "הייעוץ) במקום בתחום שנקבע בסופו.\n\n"
            "השארנו את זה גלוי בכוונה — זו בדיוק סוג התובנה שאי אפשר לקבל "
            "ממדד ROC-AUC גבוה, ורק קריאה של הפרשנות חושפת."
        )


if __name__ == "__main__":
    main()

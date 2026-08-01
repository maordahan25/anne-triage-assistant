/* ===================================================================
   אן — פאנל הנגישות (משותף לדף הצ'אט ולאזור המנהל).

   מה יש כאן: כפתור נגישות קבוע בפינה שפותח פאנל עם ארבע העדפות —
   גודל טקסט, ניגודיות גבוהה, הפחתת אנימציות והדגשת מיקוד — ובנוסף
   קישור להצהרת הנגישות. ההעדפות נשמרות ב-localStorage ומוחלות על
   <html> כ-class-ים ומשתנה CSS אחד (--a11y-text-scale), כך שכל העיצוב
   מגיב להן דרך הטוקנים ב-assets/colors.css ובלי לגעת ברכיבים.

   שתי החלטות מכוונות:
   * הקובץ נטען **סינכרונית ב-<head>** (בלי defer) ומחיל את ההעדפות
     השמורות מיד, לפני שהדפדפן מצייר. עם defer העמוד היה נצבע פעם אחת
     בהגדרות ברירת המחדל ורק אז משתנה — הבהוב שמפריע במיוחד למי שבחר
     ניגודיות גבוהה או טקסט גדול. בניית ה-UI עצמה מחכה ל-DOMContentLoaded.
   * הפאנל הוא תבנית disclosure מ-ARIA APG ולא dialog: כפתור עם
     aria-expanded + aria-controls, תוכן שמוסתר בתכונת hidden. אין
     focus trap (הפאנל אינו חוסם את העמוד), אבל Escape סוגר ומחזיר את
     המיקוד לכפתור — התנהגות שמשתמשי מקלדת מצפים לה.

   נגישות מקלדת: כל הפקדים הם button/input/label אמיתיים, ולכן Enter,
   Space, Tab וחצי הבקרה עובדים מהדפדפן ולא ממומשים כאן ידנית (2.1.1).
   =================================================================== */
"use strict";

/* ── עזרי נגישות משותפים ──────────────────────────────────────────────
   הקובץ הזה נטען בשני העמודים, ולכן הוא גם הבית של פונקציות נגישות
   שהצ'אט ואזור המנהל חולקים — כדי שלא ייווצרו שני נוסחים לאותו דבר
   (אותו עיקרון כמו dashboard/ui.py בשכבת הדשבורד). */
window.anneA11y = window.anneA11y || {};

/**
 * טקסט חלופי לאיור טיפול (1.1.1 — תוכן לא-טקסטואלי).
 * "איור" אינו תיאור: מי שאינו רואה את התמונה צריך לדעת *מה היא מדגימה*,
 * ולכן ה-alt נבנה מהשם ומשלבי ההדגמה — אותו מידע שהאיור מעביר חזותית.
 * משמש גם בבועות הצ'אט וגם בגלריית האיורים באזור המנהל.
 */
window.anneA11y.illustrationAlt = function illustrationAlt(item) {
  const name = (item && item.name) || "";
  const steps = (item && item.steps) || [];
  if (!name && !steps.length) return "איור מודרך לעזרה ראשונית";
  if (!steps.length) return `איור מודרך: ${name}`;
  return `איור מודרך — ${name}. השלבים המודגמים: ${steps.join("; ")}.`;
};

(function () {
  const STORAGE_KEY = "anne_a11y";
  const SCALE_MIN = 1;
  const SCALE_MAX = 1.6;      // 160% — מעבר לזה הפריסה בעמוד צר נשברת
  const SCALE_STEP = 0.1;
  const DEFAULTS = {
    scale: 1,
    contrast: false,
    reduceMotion: false,
    focusStrong: false,
  };

  function read() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      const scale = Number(raw.scale);
      return {
        scale: Number.isFinite(scale)
          ? Math.min(SCALE_MAX, Math.max(SCALE_MIN, scale))
          : DEFAULTS.scale,
        contrast: Boolean(raw.contrast),
        reduceMotion: Boolean(raw.reduceMotion),
        focusStrong: Boolean(raw.focusStrong),
      };
    } catch (_) {
      return { ...DEFAULTS };   // localStorage חסום/פגום — ברירת מחדל
    }
  }

  function save(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) { /* מצב פרטי בדפדפן — ההעדפה תחול לגלישה הזו בלבד */ }
  }

  let state = read();

  /** החלת ההעדפות על <html> — נקודה אחת שאחראית על המצב החזותי. */
  function apply() {
    const root = document.documentElement;
    root.style.setProperty("--a11y-text-scale", String(state.scale));
    root.classList.toggle("a11y-contrast", state.contrast);
    root.classList.toggle("a11y-reduce-motion", state.reduceMotion);
    root.classList.toggle("a11y-focus-strong", state.focusStrong);
  }

  apply();   // מיד, לפני הציור הראשון

  /* ── בניית הפאנל ─────────────────────────────────────────────────── */
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function checkboxRow(labelText, key, onChange) {
    const label = el("label", "a11y-check");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(state[key]);
    input.addEventListener("change", () => {
      state[key] = input.checked;
      save(state);
      apply();
      onChange(input.checked);
    });
    label.appendChild(input);
    label.appendChild(el("span", null, labelText));
    return { label, input };
  }

  function build() {
    if (document.querySelector(".a11y-widget")) return;

    const widget = el("div", "a11y-widget");

    const toggle = el("button", "a11y-toggle", "♿");
    toggle.type = "button";
    toggle.id = "a11y-toggle";
    toggle.setAttribute("aria-label", "הגדרות נגישות");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", "a11y-panel");

    const panel = el("div", "a11y-panel");
    panel.id = "a11y-panel";
    panel.hidden = true;
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-labelledby", "a11y-panel-title");

    // *לא* כותרת h — הפאנל הוא פקד ולא תוכן של העמוד, והוא נכנס ל-DOM
    // לפני ה-h1; h2 כאן היה יוצר היררכיית כותרות הפוכה (h2 לפני h1) ושובר
    // את 1.3.1 ו-2.4.6. aria-labelledby עובד עם כל אלמנט.
    const title = el("span", "a11y-panel-title", "הגדרות נגישות");
    title.id = "a11y-panel-title";
    panel.appendChild(title);

    /* גודל טקסט */
    const sizeGroup = el("div", "a11y-group");
    sizeGroup.appendChild(el("span", "a11y-group-title", "גודל הטקסט"));
    const sizeRow = el("div", "a11y-size-row");
    const smaller = el("button", "a11y-step", "−");   // מינוס
    smaller.type = "button";
    smaller.setAttribute("aria-label", "הקטנת הטקסט");
    const value = el("span", "a11y-size-value");
    // הקריאון מדווח את הגודל החדש בעצמו — שינוי גודל בלי משוב הוא
    // בדיוק המצב שבו משתמש קורא-מסך לא יודע אם הלחיצה עשתה משהו.
    value.setAttribute("aria-live", "polite");
    const bigger = el("button", "a11y-step", "+");
    bigger.type = "button";
    bigger.setAttribute("aria-label", "הגדלת הטקסט");

    function renderSize() {
      value.textContent = `${Math.round(state.scale * 100)}%`;
      smaller.disabled = state.scale <= SCALE_MIN + 0.001;
      bigger.disabled = state.scale >= SCALE_MAX - 0.001;
    }
    function stepSize(delta) {
      const next = Math.min(SCALE_MAX, Math.max(SCALE_MIN,
        Math.round((state.scale + delta) * 100) / 100));
      state.scale = next;
      save(state);
      apply();
      renderSize();
    }
    smaller.addEventListener("click", () => stepSize(-SCALE_STEP));
    bigger.addEventListener("click", () => stepSize(SCALE_STEP));
    sizeRow.appendChild(smaller);
    sizeRow.appendChild(value);
    sizeRow.appendChild(bigger);
    sizeGroup.appendChild(sizeRow);
    sizeGroup.appendChild(el(
      "p", "a11y-panel-note",
      "אפשר גם בזום של הדפדפן (Ctrl ומקש +) — התצוגה תומכת בשני הכלים."
    ));
    panel.appendChild(sizeGroup);

    /* מצבי תצוגה */
    const modeGroup = el("div", "a11y-group");
    modeGroup.appendChild(el("span", "a11y-group-title", "מצבי תצוגה"));
    const contrast = checkboxRow("ניגודיות גבוהה", "contrast", () => {});
    const motion = checkboxRow("הפחתת אנימציות", "reduceMotion", () => {});
    const focus = checkboxRow("הדגשת מיקוד המקלדת", "focusStrong", () => {});
    modeGroup.appendChild(contrast.label);
    modeGroup.appendChild(motion.label);
    modeGroup.appendChild(focus.label);
    panel.appendChild(modeGroup);

    /* איפוס + הצהרת נגישות */
    const actions = el("div", "a11y-group");
    const actionRow = el("div", "a11y-actions");
    const reset = el("button", "a11y-reset", "איפוס ההגדרות");
    reset.type = "button";
    reset.addEventListener("click", () => {
      state = { ...DEFAULTS };
      save(state);
      apply();
      renderSize();
      contrast.input.checked = false;
      motion.input.checked = false;
      focus.input.checked = false;
      value.textContent = `${Math.round(state.scale * 100)}%`;
    });
    actionRow.appendChild(reset);
    const statement = el("a", "a11y-statement-link", "הצהרת נגישות");
    statement.href = "/accessibility";
    actionRow.appendChild(statement);
    actions.appendChild(actionRow);
    actions.appendChild(el(
      "p", "a11y-panel-note",
      "ההעדפות נשמרות בדפדפן הזה בלבד ואינן נשלחות לשרת."
    ));
    panel.appendChild(actions);

    /* פתיחה/סגירה — disclosure: aria-expanded + hidden */
    function setOpen(open) {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
    }
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      setOpen(open);
      if (open) {
        // הפקד הפעיל הראשון: ב-100% כפתור ההקטנה *מושבת*, ופקד מושבת
        // אינו יכול לקבל מיקוד — הפוקוס היה נשאר על הכפתור ולא נכנס לפאנל.
        const first = panel.querySelector(
          "button:not([disabled]), input:not([disabled]), a[href]");
        if (first) first.focus();
      }
    });
    // Escape סוגר ומחזיר מיקוד לכפתור (2.1.2 — אין מלכודת מקלדת)
    widget.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !panel.hidden) {
        setOpen(false);
        toggle.focus();
      }
    });
    // לחיצה מחוץ לפאנל סוגרת — בלי לגזול מיקוד ממי שעובד במקלדת
    document.addEventListener("click", (event) => {
      if (!panel.hidden && !widget.contains(event.target)) setOpen(false);
    });

    widget.appendChild(panel);
    widget.appendChild(toggle);
    renderSize();

    // הווידג'ט נכנס בתחילת ה-body — כך משתמש מקלדת מגיע אליו בטאבים
    // הראשונים ולא אחרי כל תוכן העמוד — אבל **אחרי** קישור הדילוג, שחייב
    // להישאר הפקד הראשון (2.4.1: מדלגים לפני שמתעסקים בהגדרות).
    const skip = document.querySelector(".skip-link");
    if (skip && skip.parentNode === document.body) {
      document.body.insertBefore(widget, skip.nextSibling);
    } else {
      document.body.insertBefore(widget, document.body.firstChild);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", build);
  } else {
    build();
  }
})();

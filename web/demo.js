/* ===================================================================
   אן — מריץ תרחישי ההדגמה.

   המרצה בוחר תרחיש באזור המנהל, והשיחה מתנהלת מולו אוטומטית: כל הודעה
   מוקלדת לשדה הקלט (אפקט הקלדה קצר), נשלחת, והמריץ ממתין שתשובת אן
   תסתיים לפני שהוא ממשיך — כך שאפשר לקרוא כל תשובה במלואה.

   עקרון מנחה: **התרחיש הוא קלט משתמש רגיל.** המריץ אינו מדבר עם השרת
   ישירות, אינו קורא ל-sendMessage ואינו יודע דבר על SSE — הוא מקליד
   לתוך #composer-input ושולח את הטופס בדיוק כמו אדם, ואז מאזין לאירוע
   "anne:turn-done" ש-app.js משדר בסוף כל תור. אין מסלול מיוחד בשרת,
   בסוכנים או בלוג: תור של תרחיש נראה בדיוק כמו תור של משתמש אמיתי.

   **תמונות בתרחיש:** שלב attach_image מצרף תמונת הדגמה קבועה מהריפו
   אוטומטית (הרצה מקצה לקצה בלי התערבות), ושלב await_image ממתין
   לתמונה של המשתמש. שניהם עוברים דרך פקד הקובץ האמיתי של הצ'אט, ולכן
   דרך אותה ולידציה, אותה הסרת EXIF ואותו מסלול בשרת.

   **בידוד מלא של ההרצה:** לפני התור הראשון נטבע מזהה שיחה חד-פעמי
   (window.anneChat.startEphemeralSession) — לא נקרא מ-localStorage, לא
   נשמר אליו, והשרת פותח לו שיחה נקייה שאינה נרשמת בלוג האנונימי.
   בסיום ההרצה השיחה משוחררת בשרת. כך אין דליפת הקשר בין תרחישים, אין
   זיהום של השיחה הפרטית של המשתמש, ואין זיהום של נתוני הניתוח.

   התרחישים עצמם מגיעים מ-/api/demo/scenarios, שקורא את
   docs/demo_scenarios.json בזמן אמת — מקור אמת אחד, בלי עותק בקוד.
   =================================================================== */
"use strict";

/* קצב ההקלדה והשהיית הקריאה — הערכים היחידים שכדאי לכוון בהדגמה חיה. */
const TYPE_MS_PER_CHAR = 22;     // קצב "הקלדה" בשדה
const TYPE_MAX_MS = 1400;        // תקרה: הודעה ארוכה לא תוקלד לנצח
const READ_PAUSE_MS = 2600;      // המתנה אחרי סיום תשובה, לפני התור הבא
const TURN_TIMEOUT_MS = 240000;  // גבול המתנה לתור אחד (רשת/שרת תקועים)
const IMAGE_WAIT_MS = 180000;    // גבול המתנה לצירוף תמונה בשלב await_image
const ATTACH_TIMEOUT_MS = 15000; // גבול טעינת תמונת הדגמה (attach_image)

/* שמות עבריים לכלים — מפתחות המונים כפי שהם מגיעים מ-crew/tools.py. */
const TOOL_NAMES_HE = {
  search_first_aid_knowledge: "חיפוש במאגר הידע (RAG)",
  locate_place: "איתור מיקום",
  get_weather: "מזג אוויר",
  get_current_time: "שעון",
};

const demoBar = document.getElementById("demo-bar");
const demoTitle = document.getElementById("demo-title");
const demoStep = document.getElementById("demo-step");
const demoTrack = document.getElementById("demo-track");
const demoFill = document.getElementById("demo-fill");
const demoState = document.getElementById("demo-state");
const demoStopBtn = document.getElementById("demo-stop");

let stopRequested = false;
let running = false;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** המתנה לאירוע סיום התור מ-app.js (עם גבול זמן, שלא ניתקע לנצח). */
function waitForTurn() {
  return new Promise((resolve) => {
    let timer = 0;
    const onDone = (event) => {
      clearTimeout(timer);
      document.removeEventListener("anne:turn-done", onDone);
      resolve(event.detail || { payload: null, ok: false });
    };
    document.addEventListener("anne:turn-done", onDone);
    timer = setTimeout(() => {
      document.removeEventListener("anne:turn-done", onDone);
      resolve({ payload: null, ok: false, timeout: true });
    }, TURN_TIMEOUT_MS);
  });
}

/* ── שלב "המתנה לתמונה" (await_image) ────────────────────────────────
   השלב שבו המרצה (או המשתמש) מעלה תמונה משלו בזמן ההדגמה — נשאר נתמך
   לצד attach_image, לתרחישים שבהם רוצים להראות העלאה אמיתית. התמונה
   של המשתמש אינה נשמרת בשום מקום, לא בריפו ולא בשרת.

   הערה: התמונה היחידה שכן יושבת בריפו היא תמונת ההדגמה
   (assets/demo/) — היא נוצרה ב-AI במיוחד עבור הפרויקט, ולכן אין עליה
   זכויות של צד שלישי; ראה דף "רישיונות וזכויות".

   פתיחת בורר הקבצים מחייבת מחווה של משתמש (הדפדפן חוסם קליק תוכניתי
   מקוד שרץ בטיימר), ולכן המריץ מציג כרטיס עם כפתור אמיתי: הלחיצה עליו
   היא המחווה. מרגע שהתמונה נבחרה — app.js משדר "anne:image-attached",
   המריץ ממשיך אוטומטית, מקליד את ההודעה ושולח כרגיל. */
function waitForImage(step) {
  return new Promise((resolve) => {
    const card = el("section", "demo-upload");
    card.appendChild(el("h2", "demo-upload-title", "צרפו תמונה כדי להמשיך"));
    card.appendChild(el("p", "demo-upload-text", step.instruction_he
      || "בחרו תמונה מהמכשיר — התרחיש ימשיך מיד אחרי הבחירה."));

    const pick = el("button", "btn-demo-primary", "בחירת תמונה");
    pick.type = "button";
    // הכפתור רק מפעיל את פקד הקובץ האמיתי של הצ'אט — אין כאן מסלול
    // העלאה נפרד, בדיוק כמו שאין מסלול שליחה נפרד.
    pick.addEventListener("click", () => {
      const input = document.getElementById("image-input");
      if (input) input.click();
    });
    const skip = el("button", "btn-demo-ghost", "דילוג על השלב");
    skip.type = "button";

    const actions = el("div", "demo-summary-actions");
    actions.appendChild(pick);
    actions.appendChild(skip);
    card.appendChild(actions);
    document.getElementById("chat").appendChild(card);
    card.scrollIntoView({ behavior: "smooth", block: "end" });

    let timer = 0;
    const finish = (attached) => {
      clearTimeout(timer);
      clearInterval(stopPoll);
      document.removeEventListener("anne:image-attached", onAttached);
      card.remove();
      resolve(attached);
    };
    const onAttached = () => finish(true);
    document.addEventListener("anne:image-attached", onAttached);
    skip.addEventListener("click", () => finish(false));
    // עצירה יזומה של התרחיש בזמן ההמתנה — לא משאירים כרטיס תלוי.
    const stopPoll = setInterval(() => {
      if (stopRequested) finish(false);
    }, 300);
    timer = setTimeout(() => finish(false), IMAGE_WAIT_MS);
  });
}

/* ── שלב "צירוף אוטומטי" (attach_image) ──────────────────────────────
   תמונת הדגמה קבועה מהריפו מצורפת לתור בלי שאיש נוגע במסך, כדי
   שהתרחיש ירוץ מקצה לקצה מול קהל.

   העיקרון שנשמר כאן הוא בדיוק זה של שאר המריץ: **אין מסלול מיוחד.**
   התמונה נטענת כ-Blob, נארזת כ-File ומוזרקת לפקד הקובץ האמיתי של
   הצ'אט (#image-input) עם אירוע change — משם היא ממשיכה בדיוק במסלול
   של משתמש שבחר תמונה: אותה ולידציה בדפדפן, אותו base64 באותה בקשה,
   ובשרת אותה בדיקת סוג-לפי-תוכן, אותה הסרת EXIF ואותה הקטנה.

   DataTransfer הוא הדרך היחידה לכתוב ל-input.files (התכונה לקריאה
   בלבד), והוא נתמך בכל דפדפן מודרני. כישלון בטעינה אינו עוצר את
   התרחיש — התור פשוט יישלח בלי תמונה. */
async function attachDemoImage(step) {
  const input = document.getElementById("image-input");
  if (!input || !step.image_url) return false;
  try {
    const res = await fetch(step.image_url, { cache: "force-cache" });
    if (!res.ok) return false;
    const blob = await res.blob();
    const name = step.image_url.split("/").pop() || "demo.jpg";
    const file = new File([blob], name, {
      type: blob.type || "image/jpeg",
      lastModified: Date.now(),
    });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    // האירוע הוא מה שמפעיל את attachFile ב-app.js — אותו handler
    // שרץ כשאדם בוחר קובץ.
    input.dispatchEvent(new Event("change"));
    // ההצמדה עצמה אסינכרונית (FileReader): ממתינים לאירוע שהצ'אט
    // משדר בסיומה, עם גבול זמן שלא ניתקע.
    return await new Promise((resolve) => {
      const timer = setTimeout(() => {
        document.removeEventListener("anne:image-attached", onAttached);
        resolve(false);
      }, ATTACH_TIMEOUT_MS);
      const onAttached = () => {
        clearTimeout(timer);
        document.removeEventListener("anne:image-attached", onAttached);
        resolve(true);
      };
      document.addEventListener("anne:image-attached", onAttached);
    });
  } catch (_) {
    return false;
  }
}

/** אפקט הקלדה בשדה הקלט — כדי שרואים מה נכתב לפני שזה נשלח. */
async function typeIntoInput(text) {
  const input = document.getElementById("composer-input");
  const delay = Math.max(6, Math.min(TYPE_MS_PER_CHAR, TYPE_MAX_MS / text.length));
  input.value = "";
  input.focus();
  for (let i = 0; i < text.length; i++) {
    if (stopRequested) break;
    input.value = text.slice(0, i + 1);
    await sleep(delay);
  }
  input.value = text;  // תמיד ההודעה המלאה, גם אם ההקלדה קוצרה
}

/* ── מחוון ההתקדמות ──────────────────────────────────────────────────
   הסרגל מוצג *רק* בזמן שתרחיש רץ. שתי הפונקציות כאן הן שני המקומות
   היחידים שנוגעים בנראות שלו, וההסתרה היא תכונת hidden — שמסתירה
   לחלוטין (display:none) ולכן לא משאירה גובה או רווח ריק בדף. חובה
   שכלל [hidden] יישאר ב-style.css, אחרת display:flex של .demo-bar גובר
   על התכונה והסרגל נשאר על המסך (באג מאומת — ראה ההסבר בגיליון). */
function showBar(scenario, total) {
  demoTitle.textContent = scenario.title;
  demoStopBtn.disabled = false;  // תרחיש חדש — כפתור העצירה שוב פעיל
  demoStopBtn.setAttribute("aria-label", `עצירת התרחיש ${scenario.title}`);
  demoBar.hidden = false;
  updateProgress(0, total || scenario.messages.length, "מתחיל…");
}

/** הסתרת הסרגל — בסיום תרחיש, בעצירה יזומה ובכל יציאה אחרת. */
function hideBar() {
  demoBar.hidden = true;
  demoState.textContent = "";
}

function updateProgress(done, total, state) {
  const turn = Math.min(done + 1, total);
  const percent = Math.round((done / total) * 100);
  demoStep.textContent = `תור ${turn} מתוך ${total}`;
  demoFill.style.width = `${percent}%`;
  // המחוון נגיש: לא רק פס צבע. aria-valuenow נותן את ההתקדמות במספר,
  // ו-aria-valuetext נותן אותה במילים ("תור 2 מתוך 4") — כי "40%" לבדו
  // אינו אומר למשתמש קורא-מסך באיזה תור הוא נמצא.
  if (demoTrack) {
    demoTrack.setAttribute("aria-valuenow", String(percent));
    demoTrack.setAttribute("aria-valuetext", `תור ${turn} מתוך ${total}`);
  }
  // demoState הוא role="status" — השינוי כאן מוכרז בנימוס, בלי לקטוע
  if (state !== undefined) demoState.textContent = state;
}

/* ── כרטיס הסיכום בסוף התרחיש ──────────────────────────────────────── */
function summaryRow(label, value, tone) {
  const row = el("div", `demo-summary-row${tone ? " " + tone : ""}`);
  row.appendChild(el("span", "demo-summary-label", label));
  row.appendChild(el("span", "demo-summary-value", value));
  return row;
}

function renderSummary(scenario, stats, stopped, total) {
  const card = el("section", "demo-summary");
  card.appendChild(el(
    "h2", "demo-summary-title",
    stopped ? "התרחיש נעצר" : "התרחיש הסתיים",
  ));
  card.appendChild(el("p", "demo-summary-sub", scenario.title));

  const doctors = stats.doctors.length ? stats.doctors.join(" · ") : "—";
  card.appendChild(summaryRow("רופאים שטיפלו", doctors));

  const tools = Object.keys(stats.tools).length
    ? Object.entries(stats.tools)
        .map(([name, count]) =>
          `${TOOL_NAMES_HE[name] || name} ×${count}`)
        .join(" · ")
    : "לא הופעלו כלים חיצוניים";
  card.appendChild(summaryRow("כלים שהופעלו", tools));

  card.appendChild(summaryRow(
    "איורים שהוצגו",
    stats.illustrations.length ? stats.illustrations.join(" · ") : "לא הוצג איור",
  ));

  card.appendChild(summaryRow(
    "שער הבטיחות (Dr. Dexter)",
    stats.emergency
      ? `עצר את הטיפול והפנה לעזרה — דגלים: ${
          stats.redFlags.length ? stats.redFlags.join(", ") : "זוהו"}`
      : "לא נדרשה עצירה",
    stats.emergency ? "emergency" : "",
  ));

  if (stats.images) {
    card.appendChild(summaryRow(
      "תמונה שנותחה",
      `${stats.images} תמונות · ` +
      (stats.imageFeatures.join(" · ") || "ללא מאפיינים"),
    ));
  }

  card.appendChild(summaryRow(
    "תורים והיקף",
    `${stats.turns} מתוך ${total || scenario.messages.length} תורים · ` +
    `${stats.llmCalls} קריאות LLM`,
  ));

  if (scenario.demonstrates) {
    card.appendChild(el("p", "demo-summary-note", scenario.demonstrates));
  }

  const actions = el("div", "demo-summary-actions");
  const back = el("a", "btn-demo-primary", "חזרה לאזור המנהל");
  back.href = "/admin";
  actions.appendChild(back);
  const stay = el("button", "btn-demo-ghost", "המשך בצ'אט");
  stay.type = "button";
  stay.addEventListener("click", () => {
    card.remove();
    document.getElementById("composer-input").focus();
  });
  actions.appendChild(stay);
  card.appendChild(actions);

  document.getElementById("chat").appendChild(card);
  card.scrollIntoView({ behavior: "smooth", block: "end" });
}

/* ── הרצת תרחיש ────────────────────────────────────────────────────── */
async function runScenario(scenario) {
  running = true;
  stopRequested = false;
  // בידוד ההרצה: מזהה חד-פעמי -> ChatSession נקי בשרת (היסטוריה ריקה,
  // בלי רישום ללוג), ובסיום הוא משוחרר. בלי זה כל התרחישים רצו על
  // המזהה הקבוע של הדפדפן ו"ירשו" את ההיסטוריה של התרחיש הקודם.
  window.anneChat.startEphemeralSession();
  // steps הוא הרצף המלא (כולל שלב המתנה לתמונה); messages נשאר לתאימות
  // לאחור עם תרחישים/צרכנים ישנים.
  const steps = (scenario.steps && scenario.steps.length)
    ? scenario.steps
    : (scenario.messages || []).map((text) => ({
        type: "message", message_he: text,
      }));
  const total = steps.length;
  showBar(scenario, total);
  const stats = {
    turns: 0, llmCalls: 0, doctors: [], tools: {},
    illustrations: [], emergency: false, redFlags: [],
    images: 0, imageFeatures: [],
  };

  // כל היציאות מהלולאה — סיום התרחיש, עצירה יזומה, תור שלא חזר בזמן
  // וגם תקלה בלתי צפויה — עוברות ב-finally, ולכן הסרגל תמיד נעלם.
  try {
    for (let i = 0; i < total; i++) {
      if (stopRequested) break;
      const step = steps[i];
      if (step.type === "attach_image") {
        // צירוף אוטומטי — ההרצה ממשיכה מיד, בלי התערבות.
        updateProgress(i, total, "מצרף תמונת הדגמה…");
        const attached = await attachDemoImage(step);
        if (stopRequested) break;
        if (!attached) {
          updateProgress(i, total, "התמונה לא נטענה — ממשיך בלעדיה");
        }
      } else if (step.type === "await_image") {
        updateProgress(i, total, "ממתין לתמונה…");
        const attached = await waitForImage(step);
        if (stopRequested) break;
        if (!attached) {
          // דילוג/פסק זמן: ממשיכים בלי תמונה — התור עדיין תקף,
          // פשוט בלי שכבת הראייה.
          updateProgress(i, total, "ממשיך בלי תמונה");
        }
      }
      updateProgress(i, total, "מקליד…");
      await typeIntoInput(step.message_he);
      if (stopRequested) break;

      updateProgress(i, total, "אן עונה…");
      // שליחה דרך הטופס עצמו — בדיוק המסלול של משתמש אנושי.
      document.getElementById("composer-form").requestSubmit();
      const result = await waitForTurn();

      const payload = result.payload;
      if (payload) {
        stats.turns += 1;
        stats.llmCalls += payload.llm_calls || 0;
        const doctor = DOCTORS_BY_TOPIC[payload.topic];
        if (doctor && !stats.doctors.includes(doctor)) stats.doctors.push(doctor);
        Object.entries(payload.tool_usage || {}).forEach(([name, count]) => {
          stats.tools[name] = (stats.tools[name] || 0) + count;
        });
        if (payload.illustration && payload.illustration.name
            && !stats.illustrations.includes(payload.illustration.name)) {
          stats.illustrations.push(payload.illustration.name);
        }
        if (payload.image && payload.image.analyzed) {
          stats.images += 1;
          [payload.image.quality_he, payload.image.features_he]
            .filter(Boolean)
            .forEach((line) => {
              if (!stats.imageFeatures.includes(line)) {
                stats.imageFeatures.push(line);
              }
            });
        }
        if (payload.emergency) {
          stats.emergency = true;
          const doctor_he = DOCTORS_BY_TOPIC.safety;
          if (doctor_he && !stats.doctors.includes(doctor_he)) {
            stats.doctors.push(doctor_he);
          }
          (payload.red_flags || []).forEach((flag) => {
            if (!stats.redFlags.includes(flag)) stats.redFlags.push(flag);
          });
        }
      } else if (result.timeout) {
        updateProgress(i + 1, total, "התור לא הסתיים בזמן — עוצר");
        break;
      }

      updateProgress(i + 1, total, "");
      const last = i === total - 1;
      if (last || stopRequested) break;
      // השהיית קריאה — עם ספירה לאחור, כדי שברור שזו המתנה מכוונת.
      for (let left = Math.ceil(READ_PAUSE_MS / 1000); left > 0; left--) {
        if (stopRequested) break;
        updateProgress(i + 1, total, `התור הבא בעוד ${left}…`);
        await sleep(1000);
      }
    }
  } finally {
    running = false;
    hideBar();
    // כל היציאות עוברות כאן — סיום, עצירה יזומה, פסק זמן ותקלה —
    // ולכן ההקשר של ההרצה נזרק תמיד, וההודעה הבאה בצ'אט תהיה שיחה
    // רגילה חדשה של המשתמש.
    await window.anneChat.endEphemeralSession();
  }
  renderSummary(scenario, stats, stopRequested, steps.length);
}

/* עצירה: אי אפשר (ולא נכון) לבטל תור שכבר רץ בשרת — הוא כבר עלה כסף
   וימשיך להיכתב ללוג. לכן "עצור" מפסיק את *התרחיש*: אם אנחנו בין
   תורים — מיד; אם תור באוויר — בתום התשובה הנוכחית. */
if (demoStopBtn) {
  demoStopBtn.addEventListener("click", () => {
    if (!running) return;
    stopRequested = true;
    demoState.textContent = "עוצר בתום התור הנוכחי…";
    demoStopBtn.disabled = true;
  });
}

let DOCTORS_BY_TOPIC = {};

/* ── כניסה: /?demo=<id> ────────────────────────────────────────────── */
(async function initDemo() {
  const wanted = new URLSearchParams(window.location.search).get("demo");
  if (!wanted) return;

  // מנקים את הפרמטר מיד: רענון דף לא אמור להריץ את התרחיש (ולשלם) שוב.
  window.history.replaceState({}, "", window.location.pathname);

  let catalog;
  try {
    const res = await fetch("/api/demo/scenarios");
    if (!res.ok) throw new Error(`bad status ${res.status}`);
    catalog = await res.json();
  } catch (_) {
    addBubble("anne", "לא הצלחתי לטעון את תרחישי ההדגמה מהשרת.", { error: true });
    return;
  }
  DOCTORS_BY_TOPIC = catalog.doctors || {};
  const scenario = (catalog.scenarios || []).find((item) => item.id === wanted);
  if (!scenario) {
    addBubble("anne", `לא מצאתי תרחיש בשם "${wanted}" בקובץ התרחישים.`, {
      error: true,
    });
    return;
  }

  // רגע לפני ההתחלה: הודעת הפתיחה של אן כבר נטענה (init ב-app.js),
  // ונותנים למרצה שנייה לראות על מה לוחצים.
  await sleep(900);
  await runScenario(scenario);
})();

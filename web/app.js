/* ===================================================================
   אן — לוגיקת צד-הלקוח של ממשק הצ'אט.

   עקרונות:
   * מזהה משתמש אנונימי: uuid אקראי שנוצר בדפדפן פעם אחת ונשמר
     ב-localStorage. נשלח לשרת עם כל הודעה כ-user_id — כך השרת ממשיך
     את אותה ChatSession (המשכיות שיחה) והלוג האנונימי מקבץ את התורים
     תחת אותו session_id. אין בו שום פרט מזהה.
   * תשובה זורמת (SSE): התור נשלח ל-/api/chat/stream, והתשובה מופיעה
     תוך כדי שאן מנסחת אותה. עד שהניסוח מתחיל מוצג השלב הנוכחי ("בודקת
     את ההודעה…", "מתייעצת עם הצוות הרפואי…"). אירוע done נושא את
     התשובה הסופית + המקורות/האיור/הדגלים — והוא מקור האמת. אם ההזרמה
     לא זמינה מסיבה כלשהי — נפילה חזרה ל-/api/chat הרגיל.
   * כל טקסט מוצג דרך textContent/createTextNode — אין הזרקת HTML.
   * שגיאת רשת/שרת לא "מפילה" את הצ'אט — מוצגת בועת שגיאה בעברית.
   =================================================================== */
"use strict";

const USER_ID_KEY = "anne_user_id";

/* ── בידוד שיחת הדגמה ──────────────────────────────────────────────────
   הרצת תרחיש אינה שיחה של המשתמש, ולכן היא מקבלת **מזהה חד-פעמי**
   שנטבע בזיכרון בלבד: הוא לא נקרא מ-localStorage ולא נשמר אליו, השרת
   פותח לו ChatSession נקי (היסטוריה ריקה) שאינו נרשם בלוג, ובסיום
   ההרצה הוא משוחרר.

   זה השורש של דליפת ההקשר שנצפתה: כשכל התרחישים רצו על המזהה הקבוע
   של הדפדפן, השרת החזיר להם את *אותה* ChatSession — ואיתה את היסטוריית
   התרחיש הקודם. אן "זכרה" תסמינים שלא נאמרו בשיחה הנוכחית, וגם השיחה
   הפרטית של המשתמש התלכלכה בתורי ההדגמה. */
let ephemeralUserId = null;

function randomId() {
  return crypto.randomUUID
    ? crypto.randomUUID().replace(/-/g, "")
    : Array.from(crypto.getRandomValues(new Uint8Array(16)))
        .map((b) => b.toString(16).padStart(2, "0"))
        .join("");
}

/** מזהה השיחה לבקשה הנוכחית: חד-פעמי בהדגמה, ואחרת הקבוע של הדפדפן. */
function activeUserId() {
  return ephemeralUserId || getUserId();
}

/** מזהה אנונימי יציב לדפדפן (נוצר פעם אחת, ללא כל פרט מזהה). */
function getUserId() {
  let id = localStorage.getItem(USER_ID_KEY);
  if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
    id = randomId();
    localStorage.setItem(USER_ID_KEY, id);
  }
  return id;
}

/* ה-API שמריץ ההדגמה משתמש בו (web/demo.js). מוגדר על window בכוונה:
   demo.js אינו נוגע בזרימת הצ'אט — הוא רק מסמן "ההרצה מתחילה/נגמרת". */
window.anneChat = {
  /** פתיחת שיחה חד-פעמית להרצת תרחיש. מחזיר את המזהה שנטבע. */
  startEphemeralSession() {
    ephemeralUserId = randomId();
    return ephemeralUserId;
  },
  /** סיום ההרצה: השרת משחרר את השיחה, והדפדפן חוזר למזהה הרגיל. */
  async endEphemeralSession() {
    const id = ephemeralUserId;
    ephemeralUserId = null;
    if (!id) return;
    try {
      await fetch("/api/chat/session/end", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: id }),
        keepalive: true,   // עובד גם אם הדף נסגר באותו רגע
      });
    } catch (_) { /* השרת ינקה ממילא ב-LRU */ }
  },
  isEphemeral() {
    return Boolean(ephemeralUserId);
  },
};

const chatEl = document.getElementById("chat");
const formEl = document.getElementById("composer-form");
const inputEl = document.getElementById("composer-input");
const imageInputEl = document.getElementById("image-input");
const attachBtn = document.getElementById("attach-btn");
const attachPreview = document.getElementById("attach-preview");
const attachThumb = document.getElementById("attach-thumb");
const attachNameEl = document.getElementById("attach-name");
const attachRemoveBtn = document.getElementById("attach-remove");
const sendBtn = document.getElementById("send-btn");
const statusEl = document.getElementById("chat-status");
const alertEl = document.getElementById("chat-alert");

let busy = false;

/* ── הכרזות לקוראי מסך ───────────────────────────────────────────────
   שלושה אזורים, שלושה תפקידים — וזו לא קוסמטיקה אלא סדר עדיפויות:

   #chat        role="log" + aria-live="polite": הודעה *שלמה* שנוספת
                מוכרזת אחרי שהמשתמש מסיים לדבר.
   #chat-status role="status": תוויות השלב ("מתייעצת עם הצוות הרפואי…").
                בנפרד מהיומן, כי אלה עדכוני מצב חולפים ולא הודעות.
   #chat-alert  role="alert" (assertive): פסיקת חירום של ד"ר דקסטר.
                קוטעת את ההקראה הנוכחית — באפליקציה רפואית זה ההבדל בין
                "יישמע בתורו" לבין "יישמע עכשיו".

   בהזרמה (SSE) הבועה מסומנת aria-hidden כל זמן שהטקסט נבנה, ובסיום היא
   מוכנסת מחדש ל-DOM כשהיא שלמה — הכנסה מחדש היא "תוספת" מבחינת
   aria-relevant="additions", ולכן ההכרזה היא של ההודעה השלמה, פעם אחת,
   בלי שכל מקטע יוכרז לחוד ובלי טקסט מוכפל לקורא המסך. */
function announceStatus(text) {
  if (statusEl) statusEl.textContent = text || "";
}

/** הכרזת חירום מיידית. היומן מושתק לרגע כדי שלא תהיה הכרזה כפולה. */
function announceEmergency(text) {
  if (!alertEl) return;
  chatEl.setAttribute("aria-live", "off");
  alertEl.textContent = "";
  // ה-timeout הוא מה שמאלץ את קורא המסך לראות *שינוי* בתוכן האזור
  window.setTimeout(() => {
    alertEl.textContent =
      `מצב חירום — פנו לעזרה מיידית, חייגו 101. ${text || ""}`.trim();
    chatEl.setAttribute("aria-live", "polite");
  }, 60);
}

/* בועה שהוזרמה והתגלתה כחירום: הסטיילינג נקבע בבנייה, אבל בפסיקת חירום
   ה-done מגיע אחרי שהבועה כבר נבנתה — ולכן הסימון מתווסף כאן. חשוב לא
   רק חזותית: הבאנר הוא גם הטקסט שמסביר *למה* התשובה נראית אחרת. */
function markEmergency(parts) {
  parts.row.classList.add("emergency");
  parts.bubble.classList.add("bubble-emergency");
  if (parts.bubble.querySelector(".emergency-banner")) return;
  const banner = el("div", "emergency-banner");
  const icon = el("span", "emergency-icon", "⚠");
  icon.setAttribute("aria-hidden", "true");
  banner.appendChild(icon);
  banner.appendChild(el("span", null, "מצב חירום — פנו לעזרה מיידית (101)"));
  // אחרי תווית הדובר ולפני גוף התשובה — הסדר שבו הבועה נבנית מלכתחילה
  parts.bubble.insertBefore(banner, parts.body);
}

function timeNowHe() {
  return new Date().toLocaleTimeString("he-IL", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function scrollToBottom() {
  chatEl.scrollTop = chatEl.scrollHeight;
}

/** טקסט רב-שורות -> אלמנט עם שבירות שורה (ללא HTML). */
function multilineText(text) {
  const frag = document.createDocumentFragment();
  String(text).split("\n").forEach((line, i) => {
    if (i > 0) frag.appendChild(document.createElement("br"));
    frag.appendChild(document.createTextNode(line));
  });
  return frag;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** שלד בועה ריקה. מחזיר את החלקים כדי שאפשר יהיה למלא אותה בהדרגה. */
function buildBubble(role, opts = {}) {
  const row = el("div", `msg-row ${role}${opts.emergency ? " emergency" : ""}`);

  if (role === "anne") {
    const avatar = el("img", "msg-avatar");
    avatar.src = "/assets/Anne_avatae.png";
    // הדמות היא קישוט: מי מדבר נאמר בטקסט המוסתר שבתוך הבועה, ולכן
    // alt="" מונע "אן" מיותר לפני כל הודעה (1.1.1).
    avatar.alt = "";
    row.appendChild(avatar);
  }

  const stack = el("div", "msg-stack");
  const bubble = el("div", `bubble ${role === "anne" ? "bubble-anne" : "bubble-user"}`);
  if (opts.emergency) bubble.classList.add("bubble-emergency");
  if (opts.error) bubble.classList.add("bubble-error");

  // מי מדבר — נקרא ע"י קורא מסך, לא מוצג על המסך (על המסך זה ברור
  // מהצד ומהצבע של הבועה; לקורא מסך יומן בלי דוברים אינו מובן).
  bubble.appendChild(el("span", "sr-only", role === "anne" ? "אן: " : "אני: "));

  if (opts.emergency) {
    const banner = el("div", "emergency-banner");
    const icon = el("span", "emergency-icon", "⚠");
    icon.setAttribute("aria-hidden", "true");   // המשמעות בטקסט שאחריו
    banner.appendChild(icon);
    banner.appendChild(el("span", null, "מצב חירום — פנו לעזרה מיידית (101)"));
    bubble.appendChild(banner);
  }

  const body = el("div", "bubble-text");
  bubble.appendChild(body);
  stack.appendChild(bubble);
  const stamp = timeNowHe();
  const time = el("div", "msg-time", stamp);
  // השעה מוקראת עם הקדמה, אחרת קורא המסך אומר "14:03" בלי הקשר
  time.setAttribute("aria-label", `נשלח ב-${stamp}`);
  stack.appendChild(time);
  row.appendChild(stack);
  return { row, bubble, body };
}

/** התוספות שמתלוות לתשובה: דגלים אדומים, כרטיס איור ושורת מקורות. */
function decorateBubble(bubble, opts = {}) {
  // דגלים אדומים שזוהו (בפסיקת חירום) — שקיפות למשתמש.
  if (opts.redFlags && opts.redFlags.length) {
    const flags = el("div", "red-flags");
    opts.redFlags.forEach((f) => flags.appendChild(el("span", "red-flag-chip", f)));
    bubble.appendChild(flags);
  }

  // כרטיס איור מהרשימה הסגורה — תמונה, שם ושלבים ממוספרים.
  if (opts.illustration && opts.illustration.image_url) {
    const card = el("figure", "illustration-card");
    const img = el("img", "illustration-img");
    img.src = opts.illustration.image_url;
    img.alt = window.anneA11y.illustrationAlt(opts.illustration);
    img.loading = "lazy";
    card.appendChild(img);
    const cap = el("figcaption", "illustration-caption");
    cap.appendChild(el("div", "illustration-title", opts.illustration.name || ""));
    if (opts.illustration.steps && opts.illustration.steps.length) {
      const ol = el("ol", "illustration-steps");
      opts.illustration.steps.forEach((s) => ol.appendChild(el("li", null, s)));
      cap.appendChild(ol);
    }
    card.appendChild(cap);
    bubble.appendChild(card);
  }

  // מה נמצא בתמונה — שקיפות: מוצג *מה נמדד* ומה תואר, ולעולם לא
  // מסקנה רפואית (זו נשארת בגוף התשובה של אן, מהרופא המומחה).
  if (opts.image && opts.image.analyzed) {
    const note = el("div", "image-note");
    note.appendChild(el("strong", null, "מהתמונה שצירפת: "));
    const parts = [];
    if (opts.image.quality_he) parts.push(opts.image.quality_he);
    if (opts.image.features_he) parts.push(opts.image.features_he);
    note.appendChild(document.createTextNode(parts.join(" · ")));
    if (opts.image.description_he) {
      note.appendChild(document.createElement("br"));
      note.appendChild(document.createTextNode(opts.image.description_he));
    }
    note.appendChild(document.createElement("br"));
    note.appendChild(document.createTextNode(
      "התמונה נותחה כדי להוסיף הקשר לתשאול — היא אינה אבחנה, ולא נשמרה."
    ));
    bubble.appendChild(note);
  }

  // שורת מקורות — ציטוט המאגר שעליו התבססה ההמלצה (התצוגה היחידה של
  // המקור: שורות "מקור:" מוסרות מגוף התשובה בשרת).
  if (opts.sources && opts.sources.length) {
    bubble.appendChild(
      el("div", "sources-line", `מקור: ${opts.sources.join(" · ")}`)
    );
  }
}

/* ── צירוף תמונה ──────────────────────────────────────────────────────
   התמונה נבחרת בדפדפן, מוצגת בתצוגה מקדימה, ונשלחת כ-base64 *באותה
   בקשה* של ההודעה. אין "מצב תמונה" בשרת בין שתי קריאות, ואין העלאה
   נפרדת: מי ששולח הודעה שולח גם את התמונה, או שלא.

   הכלל היחיד שחשוב כאן: הקובץ נשאר בדפדפן. השרת מנתח אותו בזיכרון
   ולא שומר אותו (ראה vision/ ו-server/app.py), וגם התצוגה המקומית היא
   object URL שמשוחרר ברגע שההודעה נשלחה. */
const IMAGE_EVENT = "anne:image-attached";
const MAX_IMAGE_BYTES = 6 * 1024 * 1024;   // תואם ל-vision/ingest.py
const ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

let attachedImage = null;   // { file, dataUrl, objectUrl }

function clearAttachment() {
  if (attachedImage && attachedImage.objectUrl) {
    URL.revokeObjectURL(attachedImage.objectUrl);
  }
  attachedImage = null;
  if (imageInputEl) imageInputEl.value = "";
  if (attachPreview) attachPreview.hidden = true;
  if (attachThumb) attachThumb.removeAttribute("src");
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

async function attachFile(file) {
  if (!file) return;
  // בדיקות מקומיות מהירות — השרת בודק שוב, לפי תוכן ולא לפי סוג מוצהר.
  if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
    addBubble("anne", "אפשר לצרף תמונה מסוג JPEG, PNG או WebP בלבד.",
              { error: true });
    return;
  }
  if (file.size > MAX_IMAGE_BYTES) {
    addBubble("anne", "התמונה גדולה מדי (עד 6MB). נסו תמונה קטנה יותר.",
              { error: true });
    return;
  }
  let dataUrl;
  try {
    dataUrl = await readAsDataUrl(file);
  } catch (_) {
    addBubble("anne", "לא הצלחתי לקרוא את הקובץ. נסו תמונה אחרת.",
              { error: true });
    return;
  }
  clearAttachment();
  attachedImage = { file, dataUrl, objectUrl: URL.createObjectURL(file) };
  attachThumb.src = attachedImage.objectUrl;
  attachNameEl.textContent = `${file.name} · מוכנה לשליחה עם ההודעה`;
  attachPreview.hidden = false;
  announceStatus("תמונה צורפה להודעה");
  inputEl.focus();
  // מריץ ההדגמה מחכה לאירוע הזה בשלב await_image (demo.js) — הוא לא
  // נוגע בקלט הקובץ בעצמו, בדיוק כמו שאינו נוגע ב-sendMessage.
  document.dispatchEvent(new CustomEvent(IMAGE_EVENT, {
    detail: { name: file.name, size: file.size },
  }));
}

if (attachBtn && imageInputEl) {
  attachBtn.addEventListener("click", () => imageInputEl.click());
  imageInputEl.addEventListener("change", () => {
    attachFile(imageInputEl.files && imageInputEl.files[0]);
  });
}
if (attachRemoveBtn) {
  attachRemoveBtn.addEventListener("click", () => {
    clearAttachment();
    announceStatus("התמונה הוסרה");
    inputEl.focus();
  });
}

/** בועת הודעה שלמה. role: "anne" | "user" */
function addBubble(role, text, opts = {}) {
  const { row, bubble, body } = buildBubble(role, opts);
  // תמונה שהמשתמש צירף — מוצגת מהקובץ המקומי (object URL). היא לא
  // חוזרת מהשרת ולא נשמרת בשום מקום; זו תצוגה בדפדפן בלבד.
  if (opts.imageUrl) {
    const img = el("img", "bubble-image");
    img.src = opts.imageUrl;
    img.alt = "התמונה שצירפתי להודעה";
    body.appendChild(img);
  }
  body.appendChild(multilineText(text));
  decorateBubble(bubble, opts);
  chatEl.appendChild(row);
  // חירום בנתיב הלא-מוזרם: הכרזה קוטעת, בנוסף להכרזה הרגילה של היומן
  if (opts.emergency) announceEmergency(text);
  scrollToBottom();
  return row;
}

/** בועת "אן מקלידה…" (שלוש נקודות) + תווית השלב הנוכחי. */
function addTyping() {
  const row = el("div", "msg-row anne typing-row");
  const avatar = el("img", "msg-avatar");
  avatar.src = "/assets/Anne_avatae.png";
  avatar.alt = "";
  row.appendChild(avatar);
  const bubble = el("div", "bubble bubble-anne typing-bubble");
  for (let i = 0; i < 3; i++) bubble.appendChild(el("span", "typing-dot"));
  const label = el("span", "typing-label");
  bubble.appendChild(label);
  row.appendChild(bubble);
  // האינדיקטור עצמו מוסתר מקורא המסך: הוא אנימציה, והמצב האמיתי מוכרז
  // מ-#chat-status (role="status"). בלי זה שינוי תווית השלב היה מוכרז
  // מתוך היומן בכל שלב, וגם שלוש הנקודות היו נקראות.
  row.setAttribute("aria-hidden", "true");
  chatEl.appendChild(row);
  announceStatus("אן מנסחת תשובה…");
  scrollToBottom();
  return { row, label };
}

/** תווית שלב: על המסך בבועת ההקלדה, ולקורא המסך באזור ה-status. */
function setStage(text) {
  if (!text) return;
  announceStatus(text);
}

function setBusy(state) {
  busy = state;
  inputEl.disabled = state;
  sendBtn.disabled = state;
  if (attachBtn) attachBtn.disabled = state;
  // מודיע לטכנולוגיה מסייעת שהאזור בעבודה ולכן תוכן עשוי להשתנות
  chatEl.setAttribute("aria-busy", state ? "true" : "false");
  if (!state) inputEl.focus();
}

/* ── קריאת זרם SSE מתשובת fetch ─────────────────────────────────────
   פריים = "event: X\ndata: {...}\n\n". הקורא מפרק את החוצץ לפריימים
   שלמים ומעביר כל אחד ל-handler. */
async function readSseStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      let name = "message";
      const dataLines = [];
      frame.split("\n").forEach((line) => {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      });
      if (!dataLines.length) continue;
      let payload;
      try {
        payload = JSON.parse(dataLines.join("\n"));
      } catch (_) {
        continue; // פריים פגום — מדלגים, הזרם ממשיך
      }
      onEvent(name, payload);
    }
  }
}

/* תור בהזרמה. מחזיר:
   "ok"          — הזרם טופל (כולל error מוצהר מהשרת),
   "unsupported" — ההזרמה לא נתמכת/נדחתה לפני שהתור התחיל -> ניסיון רגיל,
   "broken"      — הזרם נקטע *אחרי* שהתור התחיל: לא חוזרים על התור (הוא
                   כבר עלה כסף ורץ בשרת), רק מודיעים למשתמש. */
async function streamTurn(text, typing, capture, imageBase64) {
  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: activeUserId(), message: text,
      image_base64: imageBase64 || null,
      demo: window.anneChat.isEphemeral(),
    }),
  });
  if (!res.ok || !res.body) return "unsupported";

  let streamed = null; // הבועה הזורמת, נוצרת עם המקטע הראשון
  let finished = false;

  await readSseStream(res, (name, payload) => {
    if (name === "stage") {
      typing.label.textContent = payload.label_he || "";
      setStage(payload.label_he);
      scrollToBottom();
    } else if (name === "delta" && payload.text) {
      if (!streamed) {
        typing.row.remove();
        streamed = buildBubble("anne");
        streamed.body.classList.add("streaming");
        // כל זמן שהטקסט נבנה — הבועה מחוץ ל"רדאר" של אזור ה-live, אחרת
        // כל מקטע היה מוכרז בנפרד ("אז", "קודם", "שטפו"...).
        streamed.row.setAttribute("aria-hidden", "true");
        chatEl.appendChild(streamed.row);
      }
      // הוספת המקטע עם שבירות שורה, בלי HTML
      streamed.body.appendChild(multilineText(payload.text));
      scrollToBottom();
    } else if (name === "done") {
      finished = true;
      if (capture) capture.payload = payload;
      announceStatus("");            // השלב הסתיים — לא משאירים "מנסחת…"
      if (streamed) {
        // התשובה הסופית מהשרת היא מקור האמת (עברה ניקוי מקורות ואיחוד
        // רווחים) — מחליפים בה את הטקסט שהוזרם ומוסיפים את התוספות.
        streamed.body.classList.remove("streaming");
        streamed.body.replaceChildren(multilineText(payload.reply_he || ""));
        if (payload.error) streamed.bubble.classList.add("bubble-error");
        decorateBubble(streamed.bubble, {
          redFlags: payload.red_flags,
          illustration: payload.illustration,
          sources: payload.sources,
          image: payload.image,
        });
        // ההודעה שלמה: מסירים את ההסתרה ומכניסים את השורה מחדש ליומן.
        // ההכנסה מחדש היא "תוספת" מבחינת aria-relevant="additions", ולכן
        // ההכרזה היא של התשובה השלמה — פעם אחת, ולא מקטע-מקטע.
        if (payload.emergency) markEmergency(streamed);
        streamed.row.removeAttribute("aria-hidden");
        chatEl.appendChild(streamed.row);
        if (payload.emergency) announceEmergency(payload.reply_he);
        scrollToBottom();
      } else {
        typing.row.remove();
        addBubble("anne", payload.reply_he, {
          emergency: payload.emergency,
          redFlags: payload.red_flags,
          illustration: payload.illustration,
          sources: payload.sources,
          image: payload.image,
          error: payload.error,
        });
      }
    }
  });

  if (!finished) {
    // הזרם נקטע לפני done.
    if (streamed) {
      streamed.body.classList.remove("streaming"); // משאירים מה שכבר נכתב
    } else {
      typing.row.remove();
      return "broken";
    }
  }
  return "ok";
}

/** תור ללא הזרמה — נתיב הגיבוי (וגם כל צרכן שאינו הדפדפן הזה). */
async function plainTurn(text, typing, capture, imageBase64) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: activeUserId(), message: text,
      image_base64: imageBase64 || null,
      demo: window.anneChat.isEphemeral(),
    }),
  });
  typing.row.remove();
  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json()).detail || "";
    } catch (_) { /* גוף לא-JSON */ }
    addBubble("anne", detail || "משהו השתבש בדרך אליי — נסו שוב עוד רגע.", {
      error: true,
    });
    return;
  }
  const data = await res.json();
  if (capture) capture.payload = data;
  addBubble("anne", data.reply_he, {
    emergency: data.emergency,
    redFlags: data.red_flags,
    illustration: data.illustration,
    sources: data.sources,
    image: data.image,
    error: data.error,
  });
}

/* התור שהסתיים משודר כאירוע DOM אחד, שנורה *תמיד* פעם אחת בדיוק — גם
   כשהתור נכשל. זה מה שמאפשר למריץ התרחישים (demo.js) לחכות לסיום
   התשובה בלי לגעת בזרימת הצ'אט עצמה: הוא לא קורא ל-sendMessage ולא
   מחליף את נתיב ה-SSE, אלא מקליד לשדה, שולח את הטופס כרגיל, ומאזין.
   detail.payload הוא מטען ה-done מהשרת (או null אם התור נכשל). */
const TURN_DONE_EVENT = "anne:turn-done";

async function sendMessage(text) {
  // התמונה נלקחת (ומנוקה מהמחבר) לפני השליחה, כדי שלא תישלח פעמיים
  // אם המשתמש שולח הודעה נוספת בזמן שהתור רץ.
  const pending = attachedImage;
  const imageBase64 = pending ? pending.dataUrl : null;
  const previewUrl = pending ? pending.objectUrl : null;
  attachedImage = null;
  if (imageInputEl) imageInputEl.value = "";
  if (attachPreview) attachPreview.hidden = true;

  addBubble("user", text, { imageUrl: previewUrl });
  const typing = addTyping();
  setBusy(true);
  const capture = { payload: null };
  try {
    const outcome = await streamTurn(text, typing, capture, imageBase64);
    if (outcome === "unsupported") {
      await plainTurn(text, typing, capture, imageBase64);
    } else if (outcome === "broken") {
      // התור רץ בשרת אבל התשובה לא הגיעה — לא מריצים אותו שוב.
      addBubble("anne", "התחברות הזרם נקטעה לפני שהתשובה הגיעה. נסו שוב.", {
        error: true,
      });
    }
  } catch (_) {
    typing.row.remove();
    addBubble("anne", "לא הצלחתי להגיע לשרת. בדקו שהשרת רץ ונסו שוב.", {
      error: true,
    });
  } finally {
    setBusy(false);
    announceStatus("");   // לא משאירים תווית שלב תלויה באוויר
    document.dispatchEvent(new CustomEvent(TURN_DONE_EVENT, {
      detail: { payload: capture.payload, ok: Boolean(capture.payload) },
    }));
  }
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text || busy) return;
  inputEl.value = "";
  sendMessage(text);
});

/* הודעת הפתיחה של אן — טקסט קבוע מהשרת (חינם, בלי LLM). */
(async function init() {
  // הבטחת מזהה כבר בטעינה — אבל *לא* כשהדף נפתח להרצת תרחיש: במצב
  // הדגמה אין נגיעה ב-localStorage בכלל, לא קריאה ולא כתיבה.
  if (!new URLSearchParams(window.location.search).has("demo")) {
    getUserId();
  }
  try {
    const res = await fetch("/api/welcome");
    if (res.ok) {
      const data = await res.json();
      addBubble("anne", data.reply_he);
    }
  } catch (_) {
    addBubble(
      "anne",
      "שלום, אני אן — אחות דיגיטלית לעזרה ראשונית. (השרת עדיין לא זמין — בדקו שהוא רץ.)",
      { error: true }
    );
  }
  inputEl.focus();
})();

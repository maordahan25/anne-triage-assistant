/* ===================================================================
   אן — לוגיקת צד-הלקוח של אזור המנהל.

   עקרונות:
   * שער התחברות זמני להדגמה: המשתמש הקבוע נבדק בשרת
     (server/app.py :: /api/admin/login), ולא כאן — הדפדפן לא מכיר את
     הסיסמה. הטוקן שמוחזר נשמר ב-sessionStorage (נמחק בסגירת הלשונית).
     זו *אינה* אבטחה אמיתית — בעתיד Supabase (משתמש+סיסמה בענן).
   * כל התוכן (אפליקציות ומסמכים) מגיע מ-/api/admin/overview — הרשימה
     הסגורה בשרת; הדפדפן לא מרכיב נתיבי קבצים בעצמו.
   * כל טקסט מוצג דרך textContent — אין הזרקת HTML (כמו ב-app.js).
   =================================================================== */
"use strict";

const TOKEN_KEY = "anne_admin_token";

const loginView = document.getElementById("login-view");
const adminView = document.getElementById("admin-view");
const loginForm = document.getElementById("login-form");
const emailInput = document.getElementById("admin-email");
const passwordInput = document.getElementById("admin-password");
const loginBtn = document.getElementById("login-btn");
const loginError = document.getElementById("login-error");
const loginErrorText = document.getElementById("login-error-text");
const togglePasswordBtn = document.getElementById("toggle-password");
const logoutBtn = document.getElementById("logout-btn");
const emailChip = document.getElementById("admin-email-chip");
const adminNote = document.getElementById("admin-note");
const appsGrid = document.getElementById("apps-grid");
const docsGrid = document.getElementById("docs-grid");
const refreshBtn = document.getElementById("refresh-btn");
const docView = document.getElementById("doc-view");
const docBody = document.getElementById("doc-body");
const docTitle = document.getElementById("doc-title");
const docSubtitle = document.getElementById("doc-subtitle");
const docKindChip = document.getElementById("doc-kind-chip");
const docDownload = document.getElementById("doc-download");
const docBackBtn = document.getElementById("doc-back");
const scenariosEntry = document.getElementById("scenarios-entry");

/* רשומות המסמכים מהסקירה — נשמרות כדי שכניסת התרחישים תפתח את המסך
   הייעודי עם אותה רשומה בדיוק שהכרטיס במסמכי הפרויקט פותח. */
let projectDocs = [];

/* ── אייקונים (SVG פנימי — בלי ספריית אייקונים חיצונית) ─────────────── */
const ICONS = {
  dashboard: ["M4 20h16", "M7 20v-9", "M12 20V6", "M17 20v-6"],
  ml: ["M4 19h16", "M5 16l4-5 3 3 5-7"],
  presentation: ["M3 4h18", "M5 4v9h14V4", "M12 13v4", "M9 20l3-3 3 3"],
  requirements: ["M8 7h11M8 12h11M8 17h11", "M4.5 7h.01M4.5 12h.01M4.5 17h.01"],
  progress: ["M4 5h16v14H4z", "M8 15v-4", "M12 15V8", "M16 15v-2"],
  test_plan: ["M7 3h10v18H7z", "M9.7 12.3l1.8 1.8 3.2-3.8"],
  demo_scenarios: ["M20 12a7.5 7.5 0 01-11.2 6.5L4.5 20l1.4-4.2A7.5 7.5 0 1120 12z"],
  licenses: ["M12 4.5l7 3v5c0 4-3 6.4-7 7.5-4-1.1-7-3.5-7-7.5v-5l7-3z",
             "M9.4 12.2l1.8 1.8 3.4-3.8"],
  sources: ["M5 5.5A1.5 1.5 0 016.5 4H19v14H6.5A1.5 1.5 0 005 19.5z", "M5 19.5V20h14v-2"],
  storyboard: ["M4 5h16v14H4z", "M4 10h16", "M10 10v9"],
  readme: ["M7 3h7l4 4v14H7z", "M14 3v4h4", "M10 13h5M10 16.5h5"],
  doc: ["M7 3h7l4 4v14H7z", "M14 3v4h4"],
};

function iconSvg(key) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  (ICONS[key] || ICONS.doc).forEach((d) => {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", d);
    svg.appendChild(path);
  });
  return svg;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

/** מעבר בין שלוש התצוגות — נקודה אחת שאחראית על מי מוצג. */
function showView(view) {
  loginView.hidden = view !== "login";
  adminView.hidden = view !== "admin";
  docView.hidden = view !== "doc";
  window.scrollTo(0, 0);  // הדף עשוי היה להיות מגולל
}

/**
 * חזרה למסך ההתחברות + ניקוי הטוקן.
 * tone="notice" למצב לא-שגיאתי (למשל טוקן שפג בטעינת הדף) — הודעה רגועה
 * ולא פס אדום, כי המשתמש לא עשה שום דבר לא נכון.
 */
function showLogin(message, tone) {
  sessionStorage.removeItem(TOKEN_KEY);
  showView("login");
  if (message) {
    loginErrorText.textContent = message;
    loginError.classList.toggle("notice", tone === "notice");
    loginError.hidden = false;
  } else {
    loginError.hidden = true;  // לא משאירים הודעה מריצה קודמת
  }
  emailInput.focus();
}

/* ── כרטיס אפליקציה (דשבורד / מודל חיזוי) ────────────────────────────
   נבנה מחדש יחד עם צד השרת. שני דברים שנשמרים כאן במפורש:

   1. **הכרטיס אינו מרכיב שום יעד בעצמו.** אין כאן מפתח -> כתובת, אין
      פורטים ואין שמות קבצים: הכל מגיע מהמפרט של אותה אפליקציה בשרת
      (server/app.py :: ADMIN_APPS -> _app_card), כך שכרטיס לא יכול
      להצביע על היעד של השני.
   2. **אין קישור/כתובת/נתיב בתצוגה.** הכתובת חיה ב-href של כפתור עדין
      שמשתלב בכרטיס, ופקודת ההרצה מועתקת בלחיצה (ויושבת ב-tooltip) —
      במקום שורת קוד עם נתיב הקובץ. */
function appCard(app) {
  const card = el("article", "app-card");

  const head = el("div", "card-head");
  const icon = el("span", "card-icon");
  icon.appendChild(iconSvg(app.key));
  head.appendChild(icon);
  head.appendChild(el("h3", "card-title", app.title));
  head.appendChild(
    el("span", `status-chip ${app.available ? "up" : "down"}`, app.status_he)
  );
  card.appendChild(head);

  card.appendChild(el("p", "card-desc", app.description));
  if (app.hint_he) card.appendChild(el("p", "card-hint", app.hint_he));

  const actions = el("div", "card-actions");

  // הכפתור העדין: אותה שפה ויזואלית של הכרטיס (קורל רך על רקע הכרטיס),
  // ולא כפתור CTA מלא שצועק. הטקסט אומר מה נפתח, ולא "פתיחה" סתם.
  const open = el("a", "card-btn", app.open_label_he || `פתיחת ${app.title}`);
  open.href = app.url;
  open.target = "_blank";
  open.rel = "noopener";
  // 2.4.4 — השם הנגיש נושא גם את מצב האפליקציה. aria-disabled לא מוגדר
  // בכוונה: הקישור *עובד* (הפורט עשוי לענות בכל רגע), ולסמן פקד תקין
  // כמושבת זו הצהרה שקרית (4.1.2).
  open.setAttribute(
    "aria-label",
    app.available
      ? `${app.open_label_he || app.title} — פתיחה בלשונית חדשה`
      : `${app.open_label_he || app.title} — פתיחה בלשונית חדשה, ${app.status_he}`
  );
  if (!app.available) open.classList.add("dim");
  actions.appendChild(open);

  // פקודת ההרצה נשארת זמינה למרצה, אך לא כטקסט על המסך: העתקה בלחיצה,
  // והפקודה המלאה ב-title (tooltip) לצורך אימות.
  if (app.command) {
    const copyBtn = el("button", "card-btn ghost", "העתקת פקודת ההרצה");
    copyBtn.type = "button";
    copyBtn.title = app.command;
    copyBtn.setAttribute(
      "aria-label", `העתקת פקודת ההרצה של ${app.title}`
    );
    copyBtn.addEventListener("click", async () => {
      const label = copyBtn.textContent;
      try {
        await navigator.clipboard.writeText(app.command);
        copyBtn.textContent = "הועתק ✓";
      } catch (_) {
        copyBtn.textContent = "לא הצלחתי להעתיק";
      }
      setTimeout(() => { copyBtn.textContent = label; }, 1800);
    });
    actions.appendChild(copyBtn);
  }

  card.appendChild(actions);
  return card;
}

/* ═══════════════════════════════════════════════════════════════════
   מציג המסמכים — מציג אחד + רנדרר לכל סוג.

   השרת (server/documents.py) מחזיר לכל מסמך `kind` אחד מששה ואת התוכן
   כבר מפורסר; כאן יושב רגיסטר שממפה kind -> פונקציית רינדור. הוספת סוג
   חדש = ערך אחד בשרת + רנדרר אחד כאן, בלי לגעת בשאר.

   שני עקרונות שנשמרים בכל הרנדררים:
   * כל טקסט נכנס דרך textContent — אין שום innerHTML. מסמכי HTML
     ו-Markdown מוצגים ב-iframe (השרת מרנדר אותם לעמוד ממותג), כך
     שה-HTML שלהם לעולם אינו מתערבב ב-DOM של אזור המנהל.
   * כל פתיחה מושכת מחדש מהשרת, שקורא מהמקור החי — אין מטמון בלקוח.
   ═══════════════════════════════════════════════════════════════════ */
const KIND_LABELS = {
  html: "מסמך HTML",
  markdown: "Markdown",
  text: "טקסט",
  requirements: "רשימת תלויות",
  checklist: "צ'קליסט",
  sources: "מאגר הידע החי",
  gallery: "גלריה חיה",
  scenarios: "תרחישי הדגמה",
  licenses: "רישיונות וזכויות",
};

const STATUS_LABELS = { active: "פעיל", partial: "חלקי", skipped: "מדולג" };
const STATUS_EMOJI = { active: "✅", partial: "🟡", skipped: "⏳" };

/** כרטיס הודעה ניטרלי — מסמך חסר, ריק, או שגיאת טעינה. */
function noticeCard(message, icon) {
  const card = el("div", "doc-notice");
  card.appendChild(el("span", "doc-notice-icon", icon || "📄"));
  card.appendChild(el("p", null, message));
  return card;
}

/* ── רנדרר: html / markdown (iframe מהשרת) ──────────────────────────── */
function renderFrame(payload) {
  const wrap = el("div", "doc-frame-wrap");
  const loading = el("p", "loading-line", "טוען את המסמך…");
  wrap.appendChild(loading);

  const frame = document.createElement("iframe");
  frame.className = "doc-frame";
  frame.src = payload.page_url;
  frame.title = payload.title;
  frame.loading = "eager";
  frame.addEventListener("load", () => loading.remove());
  frame.addEventListener("error", () => {
    loading.replaceWith(noticeCard("לא הצלחתי לטעון את המסמך.", "⚠️"));
  });
  wrap.appendChild(frame);
  return wrap;
}

/* ── רנדרר: טקסט גולמי ──────────────────────────────────────────────── */
function renderText(payload) {
  if (payload.empty) return noticeCard(payload.message_he || "הקובץ ריק.", "📭");
  const pre = el("pre", "doc-text");
  pre.textContent = payload.text || "";
  return pre;
}

/* ── רנדרר: דרישות המערכת ────────────────────────────────────────────
   קודם המסמך הזה הוצג כטקסט גולמי (105 שורות, שרובן הערות עברית) —
   נכון ובלתי קריא. השרת מפרסר אותו עכשיו לקבוצות ייעוד + חבילה לחבילה,
   וכאן זה נראה כמו מה שהוא: סיכום כמותי למעלה, ואז כרטיס לכל חבילה עם
   תג גרסה עדין. הקיבוץ מגיע מכותרות המקטעים שבמסמך עצמו — אין כאן
   רשימה שנייה שיכולה להתיישן. */
function requirementCard(pkg) {
  const card = el("article", "req-card");

  const head = el("div", "req-head");
  head.appendChild(el("code", "req-name", `${pkg.name}${pkg.extras || ""}`));
  head.appendChild(el(
    "span", `req-version ${pkg.version.kind}`, pkg.version.label_he
  ));
  card.appendChild(head);

  // מה מוצהר לעומת מה שמותקן בפועל — שתי עובדות שונות, שני שבבים.
  card.appendChild(el(
    "span", `req-installed ${pkg.installed ? "yes" : "no"}`,
    pkg.installed ? `מותקנת בסביבה: ${pkg.installed_version}`
                  : "אינה מותקנת בסביבה הזו"
  ));

  if (pkg.summary_he) card.appendChild(el("p", "req-summary", pkg.summary_he));

  // הרציונל המלא הוא תוכן המסמך (ולא תווית ממשק), ולכן נשמר במלואו —
  // מקופל, כדי שהרשימה תישאר סרוקה בקלות.
  if (pkg.rationale_he && pkg.rationale_he !== pkg.summary_he) {
    const details = el("details", "req-rationale");
    details.appendChild(el(
      "summary", null,
      pkg.rationale_shared ? "הרציונל המלא (משותף לקבוצת התלויות)"
                           : "הרציונל המלא"
    ));
    details.appendChild(el("p", null, pkg.rationale_he));
    card.appendChild(details);
  }
  return card;
}

function renderRequirements(payload) {
  const frag = document.createDocumentFragment();
  if (payload.empty || !(payload.groups || []).length) {
    frag.appendChild(noticeCard(
      payload.message_he || "לא נמצאו תלויות מוצהרות.", "📦"
    ));
    return frag;
  }
  const summary = payload.summary || {};

  const lead = el("section", "req-lead");
  lead.appendChild(el("h2", "req-lead-title", "סיכום התלויות"));
  const tiles = el("div", "req-totals");
  [
    ["חבילות מוצהרות", summary.total, ""],
    ["מותקנות בסביבה", summary.installed, "ok"],
    ["גרסאות מקובעות", summary.pinned, "warn"],
    ["טווחי גרסה", summary.ranged, ""],
    ["קבוצות ייעוד", summary.groups, "unknown"],
  ].forEach(([label, value, tone]) => {
    const tile = el("div", `total-tile ${tone}`);
    tile.appendChild(el("span", "total-value", String(value ?? 0)));
    tile.appendChild(el("span", "total-label", label));
    tiles.appendChild(tile);
  });
  lead.appendChild(tiles);
  if (payload.environment_he) {
    lead.appendChild(el("p", "req-env", payload.environment_he));
  }
  frag.appendChild(lead);

  payload.groups.forEach((group) => {
    const section = el("section", "topic-block");
    const head = el("div", "topic-head");
    head.appendChild(el("h3", "topic-title", group.title_he));
    head.appendChild(el(
      "span", "topic-count", `${group.packages.length} חבילות`
    ));
    section.appendChild(head);
    const grid = el("div", "req-grid");
    group.packages.forEach((pkg) => grid.appendChild(requirementCard(pkg)));
    section.appendChild(grid);
    frag.appendChild(section);
  });
  return frag;
}

/* ── רנדרר: צ'קליסט תוכנית הבדיקות ──────────────────────────────────── */
function renderChecklist(payload) {
  const frag = document.createDocumentFragment();
  if (payload.empty) {
    frag.appendChild(noticeCard(payload.message_he || "אין נקודות בדיקה.", "📭"));
    return frag;
  }
  const summary = payload.summary || {};
  const total = summary.total || 0;
  const statuses = ["active", "partial", "skipped"];
  const share = (status) => (total ? (summary[status] || 0) / total * 100 : 0);

  // ── האיור של המסך: מצב תוכנית הבדיקות ──────────────────────────
  // היה כאן סרגל דק (14px) עם מקרא באותיות קטנות — נכון, אבל דרש
  // מאמץ קריאה. עכשיו זו figure אחת ובולטת: שלושה מספרים גדולים,
  // סרגל עבה עם הספירה *בתוך* המקטע, ומקרא במשקל קריא. בעמוד RTL
  // המקטע הראשון מתחיל מימין — הכיוון הטבעי לקריאה, ולכן המכל
  // נשאר RTL.
  const progress = el("figure", "plan-progress");
  progress.appendChild(el("h2", "plan-progress-title",
    `סטטוס תוכנית הבדיקות — ${total} נקודות`));

  const figures = el("div", "plan-figures");
  statuses.forEach((status) => {
    const tile = el("div", `plan-figure-tile ${status}`);
    tile.appendChild(el("span", "plan-figure-value", String(summary[status] || 0)));
    tile.appendChild(el(
      "span", "plan-figure-label",
      `${STATUS_EMOJI[status]} ${STATUS_LABELS[status]}`
    ));
    tile.appendChild(el("span", "plan-figure-share",
                        `${Math.round(share(status))}% מהנקודות`));
    figures.appendChild(tile);
  });
  progress.appendChild(figures);

  // הסרגל כולו הוא תמונה אחת עם משמעות: קורא מסך מקבל אותה במשפט
  // אחד, והמקטעים שבתוכו מוסתרים ממנו (הם החלוקה הוויזואלית שלה).
  const track = el("div", "progress-track");
  track.setAttribute("role", "img");
  track.setAttribute(
    "aria-label",
    `${total} נקודות בדיקה: ` +
    statuses
      .map((status) => `${summary[status] || 0} ${STATUS_LABELS[status]}`)
      .join(", ")
  );
  statuses.forEach((status) => {
    const count = summary[status] || 0;
    if (!count) return;
    const seg = el("span", `progress-seg ${status}`);
    seg.style.width = `${share(status)}%`;
    seg.title = `${STATUS_LABELS[status]}: ${count}`;
    seg.setAttribute("aria-hidden", "true");
    // מספר בתוך המקטע — רק כשיש לו מקום, אחרת הוא נחתך ומפריע.
    if (share(status) >= 12) {
      seg.appendChild(el("span", "progress-seg-value", String(count)));
    }
    track.appendChild(seg);
  });
  progress.appendChild(track);

  const legend = el("figcaption", "progress-legend");
  statuses.forEach((status) => {
    const item = el("span", `legend-item ${status}`);
    item.appendChild(el("span", "legend-dot"));
    item.appendChild(el(
      "span", null,
      `${STATUS_EMOJI[status]} ${STATUS_LABELS[status]} — ${summary[status] || 0}`
    ));
    legend.appendChild(item);
  });
  progress.appendChild(legend);
  frag.appendChild(progress);

  const grid = el("div", "plan-grid");
  (payload.items || []).forEach((item) => {
    const card = el("article", `plan-card ${item.status}`);
    const head = el("div", "plan-head");
    head.appendChild(el("span", "plan-number", String(item.number)));
    head.appendChild(el("h3", "plan-title", item.title));
    head.appendChild(el(
      "span", `plan-chip ${item.status}`,
      `${STATUS_EMOJI[item.status]} ${item.status_he}`
    ));
    card.appendChild(head);

    if (item.active_note) {
      const note = el("p", "plan-active");
      note.appendChild(el("strong", null, "פעיל עכשיו: "));
      note.appendChild(document.createTextNode(item.active_note));
      card.appendChild(note);
    }
    if (item.bullets && item.bullets.length) {
      const list = el("ul", "plan-bullets");
      item.bullets.forEach((text) => list.appendChild(el("li", null, text)));
      card.appendChild(list);
    }
    if (item.skip_reason) {
      const skip = el("div", "plan-skip");
      skip.appendChild(el("strong", null, "סיבת הדילוג: "));
      skip.appendChild(document.createTextNode(item.skip_reason));
      card.appendChild(skip);
    }
    grid.appendChild(card);
  });
  frag.appendChild(grid);
  return frag;
}

/* ── רנדרר: מאגר הידע החי (data/) ───────────────────────────────────── */
const SOURCE_TYPE_LABELS = {
  official: "רפואי רשמי",
  commercial: "מסחרי",
  guide: "מדריך כללי",
};

function knowledgeCard(document_) {
  const card = el("article", "source-card");

  const head = el("div", "source-head");
  head.appendChild(el("h4", "source-title", document_.title));
  head.appendChild(el(
    "span", `source-chip ${document_.source_type}`,
    SOURCE_TYPE_LABELS[document_.source_type] || document_.source_type_he
  ));
  card.appendChild(head);

  const meta = el("p", "source-meta");
  if (document_.source_name) {
    meta.appendChild(document.createTextNode(document_.source_name));
  }
  card.appendChild(meta);

  if (document_.source_url) {
    const link = el("a", "source-link", "פתיחת המקור המקורי ↗");
    link.href = document_.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    card.appendChild(link);
  }

  // ארבעת המקטעים — סגורים כברירת מחדל כדי שהרשימה תישאר סרוקה בקלות.
  if (document_.sections && document_.sections.length) {
    const details = el("details", "source-sections");
    details.appendChild(el(
      "summary", null,
      `הצגת ${document_.sections.length} המקטעים של המסמך`
    ));
    document_.sections.forEach((section) => {
      const block = el("div", "source-section");
      block.appendChild(el("h5", "source-section-title", section.heading));
      const list = el("ul");
      (section.bullets || []).forEach((line) =>
        list.appendChild(el("li", null, line))
      );
      block.appendChild(list);
      details.appendChild(block);
    });
    card.appendChild(details);
  }

  // שם הקובץ אינו מוצג (אין נתיבים ושמות קבצים בתצוגה) — הוא נשאר
  // כ-tooltip בלבד, וההערה של המסמך היא מה שנקרא בפועל.
  if (document_.note) {
    const footer = el("p", "source-file", document_.note);
    footer.title = document_.file || "";
    card.appendChild(footer);
  }
  return card;
}

function renderSources(payload) {
  const frag = document.createDocumentFragment();
  if (payload.empty) {
    frag.appendChild(noticeCard(
      payload.message_he || "לא נמצאו מסמכי ידע.", "📭"
    ));
    return frag;
  }
  const totals = payload.totals || {};
  const bar = el("section", "sources-totals");
  [
    ["מסמכים במאגר", totals.documents, ""],
    ["רפואי רשמי", totals.official, "official"],
    ["מסחרי", totals.commercial, "commercial"],
    ["מדריך כללי", totals.guide, "guide"],
  ].forEach(([label, value, kind]) => {
    const tile = el("div", `total-tile ${kind}`);
    tile.appendChild(el("span", "total-value", String(value ?? 0)));
    tile.appendChild(el("span", "total-label", label));
    bar.appendChild(tile);
  });
  frag.appendChild(bar);

  (payload.topics || []).forEach((topic) => {
    const section = el("section", "topic-block");
    const head = el("div", "topic-head");
    head.appendChild(el("h3", "topic-title", topic.title_he));
    head.appendChild(el(
      "span", "topic-count", `${topic.documents.length} מסמכים`
    ));
    section.appendChild(head);
    const grid = el("div", "sources-grid");
    topic.documents.forEach((doc) => grid.appendChild(knowledgeCard(doc)));
    section.appendChild(grid);
    frag.appendChild(section);
  });
  return frag;
}

/* ── הגדלת איור (lightbox) ────────────────────────────────────────────
   האיורים בגלריה קטנים מכדי לראות בהם את מה שהם מדגימים, ולכן לחיצה על
   תמונה פותחת אותה בגודל מלא בשכבת-על אחת (השלד ב-admin.html).

   מה שנשמר כאן במפורש:
   * **הפתיחה היא כפתור אמיתי** סביב התמונה (galleryCard), ולכן Enter,
     Space, Tab והמיקוד מגיעים מהדפדפן — לא ממומשים ידנית (2.1.1).
   * **role="dialog" + aria-modal="true"**: הקריאון מתייחס לשאר העמוד
     כמוסתר, והמיקוד נלכד בין פקדי החלון (Tab מחזורי) ולא בורח לתוכן
     שמאחוריו. ביציאה המיקוד חוזר לתמונה שממנה נפתח (2.4.3).
   * **פונקציה אחת נוגעת בנראות** — showLightbox, שנקראת בדיוק פעמיים
     (פתיחה וסגירה) — והמנגנון הוא תכונת hidden, שתופסת בזכות
     [hidden] { display: none !important } בראש admin.css.
   * האנימציה מכובה תחת prefers-reduced-motion (ראה admin.css). */
const lightbox = document.getElementById("illu-lightbox");
const lightboxBackdrop = document.getElementById("illu-lightbox-backdrop");
const lightboxTitle = document.getElementById("illu-lightbox-title");
const lightboxImg = document.getElementById("illu-lightbox-img");
const lightboxSteps = document.getElementById("illu-lightbox-steps");
const lightboxClose = document.getElementById("illu-lightbox-close");

/** האלמנט שממנו נפתח החלון — המיקוד חוזר אליו בסגירה. */
let lightboxOpener = null;

function showLightbox(open) {
  if (!lightbox) return;
  lightbox.hidden = !open;
  document.body.classList.toggle("illu-lightbox-open", open);
}

function openLightbox(item, opener) {
  if (!lightbox) return;
  lightboxOpener = opener || null;
  lightboxTitle.textContent = item.name || "איור מודרך";
  lightboxImg.src = item.image_url;
  lightboxImg.alt = window.anneA11y.illustrationAlt(item);
  lightboxSteps.replaceChildren(
    ...(item.steps || []).map((step) => el("li", null, step))
  );
  showLightbox(true);
  lightboxClose.focus();
}

function closeLightbox() {
  if (!lightbox || lightbox.hidden) return;
  showLightbox(false);
  lightboxImg.removeAttribute("src");   // לא משאירים תמונה חיה ברקע
  if (lightboxOpener && document.contains(lightboxOpener)) {
    lightboxOpener.focus();
  }
  lightboxOpener = null;
}

if (lightbox) {
  lightboxClose.addEventListener("click", closeLightbox);
  lightboxBackdrop.addEventListener("click", closeLightbox);
  // Tab נשאר בתוך החלון (2.1.2 — אין מלכודת, יש מעגל). Escape מטופל
  // במאזין אחד ברמת המסמך, יחד עם Esc של המציג — ראה בתחתית הקובץ.
  lightbox.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const stops = lightbox.querySelectorAll("button:not([disabled])");
    if (!stops.length) return;
    const first = stops[0];
    const last = stops[stops.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
}

/* ── רנדרר: גלריית האיורים החיה ─────────────────────────────────────── */
function galleryCard(item) {
  const card = el("figure", "illu-card");
  if (item.image_exists) {
    // כפתור עוטף — הוא שמאפשר פתיחה גם בעכבר וגם במקלדת
    const zoom = el("button", "illu-zoom");
    zoom.type = "button";
    zoom.setAttribute("aria-label", `הגדלת האיור: ${item.name}`);
    const img = document.createElement("img");
    img.src = item.image_url;
    // תיאור מלא, לא רק שם — אותה פונקציה משותפת של הצ'אט (web/a11y.js)
    img.alt = window.anneA11y.illustrationAlt(item);
    img.loading = "lazy";          // גלריה של 20 תמונות — טעינה עצלה
    img.decoding = "async";
    // קובץ שנמחק אחרי שהקטלוג נקרא: מסגרת חלופית במקום תמונה שבורה
    // (והכפתור יורד איתה — אין מה להגדיל).
    img.addEventListener("error", () => {
      zoom.replaceWith(el("div", "illu-missing", "התמונה חסרה"));
    });
    zoom.addEventListener("click", () => openLightbox(item, zoom));
    zoom.appendChild(img);
    card.appendChild(zoom);
  } else {
    card.appendChild(el("div", "illu-missing", "התמונה חסרה"));
  }

  const caption = el("figcaption", "illu-caption");
  caption.appendChild(el("span", "illu-name", item.name));
  caption.appendChild(el("code", "illu-id", item.id));
  card.appendChild(caption);

  if (item.steps && item.steps.length) {
    const details = el("details", "illu-steps");
    details.appendChild(el("summary", null, `${item.steps.length} שלבים`));
    const list = el("ol");
    item.steps.forEach((step) => list.appendChild(el("li", null, step)));
    details.appendChild(list);
    card.appendChild(details);
  }
  return card;
}

function renderGallery(payload) {
  const frag = document.createDocumentFragment();
  if (!payload.available || payload.empty) {
    frag.appendChild(noticeCard(
      payload.message_he || "אין איורים להצגה.", "🖼️"
    ));
    return frag;
  }
  frag.appendChild(el(
    "p", "doc-lead",
    `${payload.total} איורים מודרכים ב-${payload.categories.length} קטגוריות, ` +
    "מתוך הרשימה הסגורה שהרופאים בוחרים ממנה."
  ));
  payload.categories.forEach((category) => {
    const section = el("section", "topic-block");
    const head = el("div", "topic-head");
    head.appendChild(el("h3", "topic-title", category.name));
    head.appendChild(el(
      "span", "topic-count", `${category.items.length} איורים`
    ));
    section.appendChild(head);
    const grid = el("div", "illu-grid");
    category.items.forEach((item) => grid.appendChild(galleryCard(item)));
    section.appendChild(grid);
    frag.appendChild(section);
  });
  return frag;
}

/* ── רנדרר: תרחישי ההדגמה + כפתור ההרצה ─────────────────────────────
   אותה פונקציה משרתת שני מקומות: מקטע "תרחישי הדגמה" בלוח המנהל,
   והמסמך "תרחישי הדגמה" במציג. מקור אחד, תצוגה אחת. */
function scenarioCard(scenario) {
  const card = el("article", "scenario-card");

  const head = el("div", "scenario-head");
  head.appendChild(el("h3", "scenario-title", scenario.title));
  if (scenario.doctor) {
    head.appendChild(el("span", "scenario-doctor", scenario.doctor));
  }
  card.appendChild(head);

  card.appendChild(el(
    "p", "scenario-turns",
    `${scenario.turns} תורים · שיחה מתפתחת`
  ));
  if (scenario.demonstrates) {
    const what = el("p", "scenario-demo");
    what.appendChild(el("strong", null, "מה מדגים: "));
    what.appendChild(document.createTextNode(scenario.demonstrates));
    card.appendChild(what);
  }

  // ההודעות עצמן — סגורות כברירת מחדל; המרצה יכול להציץ מראש.
  // steps נושא את הרצף המלא: הודעות, וגם שלב שבו התרחיש עוצר ומבקש
  // מהמרצה לצרף תמונה (await_image). מסומן, כדי שלא יופתע בהדגמה.
  const details = el("details", "scenario-messages");
  details.appendChild(el("summary", null, "ההודעות שיישלחו"));
  const list = el("ol");
  const steps = (scenario.steps && scenario.steps.length)
    ? scenario.steps
    : (scenario.messages || []).map((text) => ({
        type: "message", message_he: text,
      }));
  const STEP_TAGS = {
    await_image: "עצירה לצירוף תמונה",
    attach_image: "תמונת הדגמה מצורפת אוטומטית",
  };
  steps.forEach((step) => {
    const item = el("li", null, step.message_he);
    if (STEP_TAGS[step.type]) {
      item.appendChild(el("span", "scenario-step-tag", STEP_TAGS[step.type]));
    }
    list.appendChild(item);
  });
  details.appendChild(list);
  if (scenario.expectation_he) {
    details.appendChild(el("p", "scenario-expect", scenario.expectation_he));
  }
  card.appendChild(details);

  const actions = el("div", "scenario-actions");
  const run = el("button", "btn-primary btn-small", "▶ הרץ תרחיש");
  run.type = "button";
  // ההרצה עצמה קורית בדף הצ'אט: הוא מקבל את מזהה התרחיש ומריץ אותו
  // כקלט משתמש רגיל (web/demo.js). כאן רק מנווטים.
  run.addEventListener("click", () => {
    window.location.href = `/?demo=${encodeURIComponent(scenario.id)}`;
  });
  actions.appendChild(run);
  actions.appendChild(el(
    "span", "scenario-cost",
    `≈ ${scenario.turns * 4} קריאות LLM`
  ));
  card.appendChild(actions);
  return card;
}

function renderScenarios(payload) {
  const frag = document.createDocumentFragment();
  if (!payload.available || !(payload.scenarios || []).length) {
    frag.appendChild(noticeCard(
      payload.message_he || "אין תרחישי הדגמה מוגדרים.", "🎬"
    ));
    return frag;
  }
  const grid = el("div", "scenarios-grid");
  payload.scenarios.forEach((scenario) =>
    grid.appendChild(scenarioCard(scenario))
  );
  frag.appendChild(grid);
  return frag;
}

/* ── רנדרר: רישיונות וזכויות ─────────────────────────────────────────
   התצוגה עונה על שאלה אחת: האם יש בפרויקט חבילה שאינה בשימוש חופשי.
   לכן היא נפתחת בפסק דין, ממשיכה בסיכום כמותי, ומציגה קודם את מה
   שדורש תשומת לב (קופילפט חזק / לא מזוהה) ורק אחר כך את המתירניות.
   כל הנתונים מגיעים מהשרת מסווגים — כאן רק תצוגה. */
/** ניסוח יחיד/רבים — התצוגה בעברית, ו-"1 חבילות" נראה שגוי. */
function packagesHe(count) {
  return count === 1 ? "חבילה אחת" : `${count} חבילות`;
}

function licenseSummary(summary, categories) {
  const bar = el("section", "lic-totals");
  const tiles = [["חבילות מותקנות", summary.total, ""]];
  categories.forEach((category) => {
    tiles.push([category.label_he, category.count, category.tone]);
  });
  tiles.forEach(([label, value, tone]) => {
    const tile = el("div", `total-tile ${tone}`);
    tile.appendChild(el("span", "total-value", String(value ?? 0)));
    tile.appendChild(el("span", "total-label", label));
    bar.appendChild(tile);
  });
  return bar;
}

function packageRow(pkg) {
  const row = el("div", `lic-row ${pkg.category}${pkg.verified ? " verified" : ""}`);
  const head = el("div", "lic-row-head");
  head.appendChild(el("span", "lic-name", pkg.name));
  head.appendChild(el("span", "lic-version", pkg.version || ""));
  if (pkg.declared) {
    head.appendChild(el("span", "lic-flag", "תלות מוצהרת"));
  }
  // הבחנה שחייבת להישאר גלויה: רישיון שהחבילה הצהירה עליו מול רישיון
  // שאומת ידנית מול המאגר מפני שהמטא-דאטה שותקת.
  if (pkg.verified) {
    head.appendChild(el("span", "lic-flag verified", "אומת ידנית"));
  }
  row.appendChild(head);
  row.appendChild(el("code", "lic-license", pkg.license_raw || "—"));
  // על מה הסיווג נשען אצל *החבילה הזו* — SPDX, classifier, טקסט חופשי,
  // אימות ידני או שום הצהרה. זו התשובה ל"אולי משהו התחמק מהסריקה".
  const meta = [`הצהרה: ${pkg.declaration_he || "—"}`];
  if (pkg.bundled_licenses > 1) {
    meta.push(`מצרפת ${pkg.bundled_licenses} רישיונות של תלויות`);
  }
  row.appendChild(el("span", "lic-declaration", meta.join(" · ")));
  if (pkg.matched_he) row.appendChild(el("span", "lic-note", pkg.matched_he));
  if (pkg.source_url) {
    const link = el("a", "lic-source", "קובץ הרישיון שאומת ↗");
    link.href = pkg.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    row.appendChild(link);
  }
  return row;
}

function licenseCategoryBlock(category) {
  const section = el("section", `lic-block ${category.tone}`);

  const head = el("div", "lic-block-head");
  head.appendChild(el("span", `lic-chip ${category.tone}`, category.label_he));
  head.appendChild(el("span", "lic-examples", category.examples_he));
  head.appendChild(el("span", "lic-count", packagesHe(category.count)));
  section.appendChild(head);
  section.appendChild(el("p", "lic-meaning", category.meaning_he));

  if (!category.count) {
    section.appendChild(el("p", "lic-empty", "אין חבילות בקטגוריה הזו ✓"));
    return section;
  }
  // מה שדורש תשומת לב פתוח, וגם רשימה קצרה (עד 8) — אין טעם לקפל שלוש
  // חבילות. רק הקטגוריה המתירנית, שהיא הרוב המכריע, נשארת מקופלת.
  const attention = category.tone === "danger" || category.tone === "unknown"
    || category.count <= 8;
  const list = el("div", "lic-list");
  category.packages.forEach((pkg) => list.appendChild(packageRow(pkg)));
  if (attention) {
    section.appendChild(list);
  } else {
    const details = el("details", "lic-details");
    details.appendChild(el(
      "summary", null, `הצגת ${packagesHe(category.count)}`
    ));
    details.appendChild(list);
    section.appendChild(details);
  }
  return section;
}

/* על מה הסיווג נשען — נפרד מהסיווג עצמו. "0 לא מזוהות" זו תשובה חלשה
   אם חצי מהחבילות מצהירות בטקסט חופשי, ולכן הפירוט הזה מוצג במפורש. */
function declarationQuality(payload) {
  const section = el("section", "lic-quality");
  section.appendChild(el("h3", "lic-section-title", "על מה הסיווג נשען"));

  const labels = payload.declaration_labels_he || {};
  const counts = payload.declaration_summary || {};
  const list = el("div", "lic-quality-row");
  Object.entries(counts).forEach(([tier, count]) => {
    const item = el("span", `lic-quality-item ${tier}`);
    item.appendChild(el("strong", null, String(count)));
    item.appendChild(document.createTextNode(` ${labels[tier] || tier}`));
    list.appendChild(item);
  });
  section.appendChild(list);
  if (payload.declaration_note_he) {
    section.appendChild(el("p", "lic-meaning", payload.declaration_note_he));
  }

  // חבילות שמצרפות רישיונות של ספריות שנבנו לתוכן (בינאריים).
  if ((payload.bundling || []).length) {
    const bundling = el("p", "lic-meaning");
    bundling.appendChild(el("strong", null, "רישיונות של תלויות מצורפות: "));
    bundling.appendChild(document.createTextNode(
      payload.bundling
        .map((item) => `${item.name} (${item.count})`)
        .join(" · ") + ". " + (payload.bundling_note_he || "")
    ));
    section.appendChild(bundling);
  }
  return section;
}

function contentRightsBlock(content) {
  const wrap = el("section", "lic-content");
  wrap.appendChild(el("h3", "lic-section-title", "זכויות התוכן והנכסים"));

  const knowledge = content.knowledge || {};
  const first = el("article", `lic-content-card${knowledge.complete ? " ok" : ""}`);
  first.appendChild(el("h4", null, "מאגר הידע של אן"));
  first.appendChild(el("p", null, knowledge.policy_he || ""));
  first.appendChild(el("p", "lic-evidence", knowledge.evidence_he || ""));
  const totals = knowledge.totals || {};
  first.appendChild(el(
    "p", "lic-breakdown",
    `סוגי מקורות: ${totals.official || 0} רפואי רשמי · ` +
    `${totals.commercial || 0} מסחרי · ${totals.guide || 0} מדריך כללי`
  ));
  wrap.appendChild(first);

  const illustrations = content.illustrations || {};
  const second = el(
    "article", `lic-content-card${illustrations.recorded ? " ok" : " review"}`
  );
  second.appendChild(el("h4", null, "האיורים המודרכים"));
  second.appendChild(el("p", null, illustrations.policy_he || ""));
  second.appendChild(el(
    "p", "lic-breakdown",
    `${illustrations.total || 0} איורים בקטלוג · ` +
    `${illustrations.images_present || 0} קובצי תמונה קיימים`
  ));
  second.appendChild(el("p", "lic-evidence", illustrations.evidence_he || ""));
  wrap.appendChild(second);

  // תמונות ההדגמה שבריפו — נכס תוכן לכל דבר, ולכן מוצהר כאן ולא נשאר
  // "תמונה שיושבת בתיקייה" בלי מקור.
  const demoImages = content.demo_images;
  if (demoImages) {
    const third = el("article", "lic-content-card ok");
    third.appendChild(el("h4", null, "תמונות ההדגמה"));
    third.appendChild(el("p", null, demoImages.policy_he || ""));
    third.appendChild(el(
      "p", "lic-breakdown",
      `${demoImages.total || 0} תמונות הדגמה בפרויקט`
    ));
    third.appendChild(el("p", "lic-evidence", demoImages.evidence_he || ""));
    wrap.appendChild(third);
  }
  return wrap;
}

function renderLicenses(payload) {
  const frag = document.createDocumentFragment();

  const verdict = el("section", `lic-verdict ${payload.verdict_tone || ""}`);
  verdict.appendChild(el("h3", null, "האם יש חבילה שאינה בשימוש חופשי?"));
  verdict.appendChild(el("p", null, payload.verdict_he || ""));
  if (payload.environment_he) {
    verdict.appendChild(el("p", "lic-env", payload.environment_he));
  }
  frag.appendChild(verdict);

  if (payload.empty) {
    frag.appendChild(noticeCard(
      payload.message_he || "לא נמצאו חבילות לסריקה.", "📦"
    ));
  } else {
    frag.appendChild(licenseSummary(payload.summary || {},
                                    payload.categories || []));
    frag.appendChild(declarationQuality(payload));
    (payload.categories || []).forEach((category) =>
      frag.appendChild(licenseCategoryBlock(category))
    );
  }

  // חבילה שמוצהרת בהצהרת התלויות אך אינה מותקנת: הרישיון שלה כלל לא
  // נבדק, וזה הבדל שחייב להיות גלוי ולא להיעלם בין 148 שורות.
  if ((payload.declared_missing || []).length) {
    const missing = el("section", "lic-block unknown");
    const missingHead = el("div", "lic-block-head");
    missingHead.appendChild(el(
      "span", "lic-chip unknown", "מוצהרות אך לא מותקנות"
    ));
    missing.appendChild(missingHead);
    missing.appendChild(el(
      "p", "lic-meaning",
      "החבילות האלה מוצהרות בדרישות המערכת אך אינן מותקנות בסביבה " +
      "הזו — הרישיון שלהן לא נסרק: " + payload.declared_missing.join(" · ")
    ));
    frag.appendChild(missing);
  }

  if (payload.content) frag.appendChild(contentRightsBlock(payload.content));

  if (payload.disclaimer_he) {
    const note = el("section", "lic-disclaimer");
    note.appendChild(el("strong", null, "סייג: "));
    note.appendChild(document.createTextNode(payload.disclaimer_he));
    frag.appendChild(note);
  }
  return frag;
}

/** הרגיסטר: kind (מהשרת) -> רנדרר. */
const DOC_RENDERERS = {
  html: renderFrame,
  markdown: renderFrame,
  text: renderText,
  requirements: renderRequirements,
  checklist: renderChecklist,
  sources: renderSources,
  gallery: renderGallery,
  scenarios: renderScenarios,
  licenses: renderLicenses,
};

/** פתיחת מסמך במציג: משיכה מהשרת -> בחירת רנדרר -> רינדור. */
async function openDocument(doc) {
  showView("doc");
  docTitle.textContent = doc.title;
  docSubtitle.textContent = doc.description || "";
  docKindChip.hidden = true;
  docDownload.hidden = true;
  docBody.replaceChildren(el("p", "loading-line", "טוען את המסמך…"));

  const token = getToken();
  let payload;
  try {
    const res = await fetch(
      `/api/admin/doc/${encodeURIComponent(doc.key)}/view` +
      `?token=${encodeURIComponent(token)}`
    );
    if (res.status === 401) {
      showLogin("ההתחברות פגה — נא להתחבר שוב.", "notice");
      return;
    }
    if (!res.ok) throw new Error(`bad status ${res.status}`);
    payload = await res.json();
  } catch (_) {
    docBody.replaceChildren(noticeCard(
      "לא הצלחתי לטעון את המסמך. בדקו שהשרת רץ ונסו שוב.", "⚠️"
    ));
    return;
  }

  docTitle.textContent = payload.title || doc.title;
  const notes = [payload.description, payload.live_note_he].filter(Boolean);
  docSubtitle.textContent = notes.join(" · ");
  if (KIND_LABELS[payload.kind]) {
    docKindChip.textContent = KIND_LABELS[payload.kind];
    docKindChip.hidden = false;
  }
  if (payload.download_url) {
    docDownload.href = payload.download_url;
    docDownload.target = "_blank";
    docDownload.rel = "noopener";
    // תווית ידידותית בלבד; שם הקובץ נשאר ב-tooltip (אין שמות קבצים בתצוגה).
    docDownload.textContent = "הורדת הקובץ המקורי";
    docDownload.title = payload.download_name || "";
    docDownload.setAttribute(
      "aria-label", `הורדת הקובץ המקורי של ${payload.title || doc.title}`
    );
    docDownload.hidden = false;
  }

  // מקור חסר — הודעה מסודרת, לא מסך שבור (גם הרנדררים עצמם מטפלים בריק).
  if (!payload.available) {
    docBody.replaceChildren(noticeCard(
      payload.message_he || "המסמך אינו זמין כרגע.", "📄"
    ));
    return;
  }
  const renderer = DOC_RENDERERS[payload.kind];
  if (!renderer) {
    docBody.replaceChildren(noticeCard(
      `אין מציג לסוג המסמך "${payload.kind}".`, "❓"
    ));
    return;
  }
  docBody.replaceChildren(renderer(payload));
}

/* ── כרטיס מסמך פרויקט (ברשת אזור המנהל) ───────────────────────────── */
function docCard(doc) {
  const card = el("button", `doc-card${doc.exists ? "" : " missing"}`);
  card.type = "button";
  if (doc.exists) {
    card.addEventListener("click", () => openDocument(doc));
  } else {
    card.disabled = true;
  }

  const head = el("div", "card-head");
  const icon = el("span", "card-icon");
  icon.appendChild(iconSvg(doc.key));
  head.appendChild(icon);
  head.appendChild(el("h3", "card-title", doc.title));
  card.appendChild(head);

  card.appendChild(el("p", "card-desc", doc.description));

  // שורת המטא בעברית בלבד: סוג המסמך וגודלו. שם הקובץ אינו מוצג —
  // הוא נשאר כ-tooltip על הכרטיס כולו, למי שמחפש את המקור בדיסק.
  card.title = doc.file_name || "";
  card.appendChild(el(
    "p", "doc-meta",
    doc.exists
      ? [KIND_LABELS[doc.kind] || "מסמך", doc.size_he].filter(Boolean).join(" · ")
      : "המסמך אינו נמצא במקומו"
  ));

  card.appendChild(el("span", "doc-open", doc.exists ? "הצגה בממשק" : "לא זמין"));
  return card;
}

/* ── טעינת אזור המנהל ──────────────────────────────────────────────── */
async function loadOverview() {
  const token = getToken();
  if (!token) {
    showLogin();
    return;
  }
  appsGrid.replaceChildren(el("p", "loading-line", "טוען…"));
  docsGrid.replaceChildren();

  let data;
  try {
    const res = await fetch(
      `/api/admin/overview?token=${encodeURIComponent(token)}`
    );
    // טוקן ישן (למשל אחרי הפעלה מחדש של השרת — הטוקנים בזיכרון התהליך):
    // מנקים אותו ומחזירים למסך ההתחברות בהודעה רגועה. לא נתקעים.
    if (res.status === 401) {
      showLogin("ההתחברות פגה — נא להתחבר שוב.", "notice");
      return;
    }
    if (!res.ok) throw new Error(`bad status ${res.status}`);
    data = await res.json();
  } catch (_) {
    // כשל רשת/שרת (לא 401): אם המשתמש כבר בתוך אזור המנהל (רענון מצב) —
    // לא מנתקים אותו בגלל תקלת רשת חולפת, רק מודיעים. אם הוא עדיין
    // בהתחברות — חוזרים לשם עם הסבר, ולא משאירים תצוגת מנהל ריקה.
    const message = "לא הצלחתי לטעון את אזור המנהל. בדקו שהשרת רץ ונסו שוב.";
    if (adminView.hidden) showLogin(message);
    else appsGrid.replaceChildren(el("p", "loading-line", message));
    return;
  }

  showView("admin");
  emailChip.textContent = data.email || "";
  adminNote.textContent = data.note_he || "";
  projectDocs = data.docs || [];
  appsGrid.replaceChildren(...(data.apps || []).map(appCard));
  // התרחישים אינם מקבלים כרטיס ברשת המסמכים: יש להם מקטע משלהם למעלה,
  // עם כרטיס כניסה למסך הייעודי — כפתור שני לאותו מסך הוא רק כפילות.
  // הרשומה עצמה נשמרת ב-projectDocs, כך שכרטיס הכניסה פותח את אותו
  // מסמך בדיוק (openScenariosScreen).
  docsGrid.replaceChildren(
    ...projectDocs
      .filter((doc) => doc.key !== SCENARIOS_DOC_KEY)
      .map(docCard)
  );
  loadScenarios();
}

/* ── כניסת התרחישים בלוח ───────────────────────────────────────────
   התרחישים יש להם מסך ייעודי (אותו מציג, kind="scenarios"), ולכן הלוח
   מציג כרטיס אחד שמוביל אליו ולא את הרשימה עוד פעם: קודם אותם חמישה
   תרחישים — ההודעות, "מה מדגים" וכפתורי ההרצה — נרנדרו גם בלוח וגם
   במסך, שתי תצוגות של אותו מקור אמת שהיה צריך לתחזק פעמיים.
   המספרים בכרטיס נטענים מ-/api/demo/scenarios (חינם, בלי LLM) — אותו
   מקור שממנו המריץ בצ'אט שואב. */
const SCENARIOS_DOC_KEY = "demo_scenarios";

/** פתיחת המסך הייעודי של התרחישים (רשומת המסמך אם נטענה, אחרת המפתח). */
function openScenariosScreen() {
  const doc = projectDocs.find((item) => item.key === SCENARIOS_DOC_KEY) || {
    key: SCENARIOS_DOC_KEY,
    title: "תרחישי הדגמה",
    description: "",
  };
  openDocument(doc);
}

function scenariosEntryCard(catalog) {
  const card = el("article", "app-card");

  const head = el("div", "card-head");
  const icon = el("span", "card-icon");
  icon.appendChild(iconSvg(SCENARIOS_DOC_KEY));
  head.appendChild(icon);
  head.appendChild(el("h3", "card-title", "מסך תרחישי ההדגמה"));
  head.appendChild(el(
    "span", "status-chip up",
    `${catalog.scenarios.length} תרחישים`
  ));
  card.appendChild(head);

  card.appendChild(el(
    "p", "card-desc",
    `${catalog.total_turns} תורים בסך הכול — תרחיש לכל רופא מומחה ואחד ` +
    "למסלול הבטיחות. במסך עצמו: מה כל תרחיש מדגים, ההודעות שיישלחו " +
    "וכפתור הרצה לכל אחד."
  ));

  const actions = el("div", "card-actions");
  const open = el("button", "btn-primary btn-small", "פתיחת מסך התרחישים");
  open.type = "button";
  open.addEventListener("click", openScenariosScreen);
  actions.appendChild(open);
  card.appendChild(actions);
  return card;
}

async function loadScenarios() {
  if (!scenariosEntry) return;
  scenariosEntry.replaceChildren(el("p", "loading-line", "טוען תרחישים…"));
  let catalog;
  try {
    const res = await fetch("/api/demo/scenarios");
    if (!res.ok) throw new Error(`bad status ${res.status}`);
    catalog = await res.json();
  } catch (_) {
    scenariosEntry.replaceChildren(noticeCard(
      "לא הצלחתי לטעון את תרחישי ההדגמה.", "🎬"
    ));
    return;
  }
  // קובץ חסר/פגום/ריק: הודעה במקום כרטיס שמוביל למסך ריק.
  if (!catalog.available || !(catalog.scenarios || []).length) {
    scenariosEntry.replaceChildren(noticeCard(
      catalog.message_he || "אין תרחישי הדגמה מוגדרים.", "🎬"
    ));
    return;
  }
  scenariosEntry.replaceChildren(scenariosEntryCard(catalog));
}

/* ── התחברות / יציאה ───────────────────────────────────────────────── */
loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  loginBtn.disabled = true;
  const previousLabel = loginBtn.textContent;
  loginBtn.textContent = "מתחבר…";
  try {
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: emailInput.value.trim(),
        password: passwordInput.value,
      }),
    });
    if (!res.ok) {
      // חשוב להבחין בין "פרטים שגויים" (401) לכל כשל אחר: בבאג מאומת
      // תקלת שרת (500) הוצגה למשתמש כ"אימייל או סיסמה שגויים", וכך הבאג
      // האמיתי נשאר בלתי נראה. כאן כל מצב מקבל הודעה משלו, עם קוד המצב.
      let detail = "";
      try {
        const body = await res.json();
        // ב-422 של FastAPI, detail הוא מערך של שגיאות ולא מחרוזת.
        if (typeof body.detail === "string") detail = body.detail;
      } catch (_) { /* גוף לא-JSON (למשל 500 של starlette) */ }
      if (res.status === 401) {
        loginErrorText.textContent = detail || "אימייל או סיסמה שגויים";
      } else if (res.status === 422) {
        loginErrorText.textContent = "נא למלא אימייל וסיסמה.";
      } else if (res.status === 503) {
        // לא הוגדרו פרטי כניסה בסביבה. זו אינה טעות של מי שמקליד, ולכן
        // מוצגת ההודעה של השרת (מה להגדיר ואיפה) ולא "סיסמה שגויה".
        loginErrorText.textContent = detail || "לא הוגדרו פרטי כניסה.";
      } else {
        loginErrorText.textContent =
          `שגיאת שרת (${res.status}) — לא הצלחתי לבדוק את הפרטים. ` +
          `בדקו את הטרמינל של השרת ונסו שוב.`;
      }
      loginError.hidden = false;
      return;
    }
    const data = await res.json();
    sessionStorage.setItem(TOKEN_KEY, data.token);
    passwordInput.value = "";
    await loadOverview();
  } catch (_) {
    loginErrorText.textContent = "לא הצלחתי להגיע לשרת. בדקו שהשרת רץ ונסו שוב.";
    loginError.hidden = false;
  } finally {
    loginBtn.disabled = false;
    loginBtn.textContent = previousLabel;
  }
});

togglePasswordBtn.addEventListener("click", () => {
  const showing = passwordInput.type === "text";
  passwordInput.type = showing ? "password" : "text";
  togglePasswordBtn.setAttribute(
    "aria-label", showing ? "הצגת הסיסמה" : "הסתרת הסיסמה"
  );
});

logoutBtn.addEventListener("click", async () => {
  const token = getToken();
  try {
    await fetch(`/api/admin/logout?token=${encodeURIComponent(token)}`, {
      method: "POST",
    });
  } catch (_) { /* יציאה מקומית גם אם השרת לא זמין */ }
  showLogin();
});

if (refreshBtn) refreshBtn.addEventListener("click", loadOverview);

// חזרה מהמציג לאזור המנהל. ה-iframe מוסר מה-DOM (ולא רק מוסתר) כדי
// שמסמך כבד — המצגת היא ~270KB — לא יישאר חי ברקע.
if (docBackBtn) {
  docBackBtn.addEventListener("click", () => {
    closeLightbox();   // שכבת ההגדלה לא נשארת מעל אזור המנהל
    docBody.replaceChildren();
    showView("admin");
  });
}

// Esc — מאזין אחד לכל השכבות, בסדר מהפנימית לחיצונית. שכבת הגדלת
// האיור נסגרת ראשונה ו*במקום* המציג: שני מאזינים נפרדים היו רצים על
// אותה הקשה וסוגרים גם את התמונה וגם את המסמך שמאחוריה.
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (lightbox && !lightbox.hidden) {
    closeLightbox();
    return;
  }
  if (!docView.hidden) {
    docBody.replaceChildren();
    showView("admin");
  }
});

/* מצב פתיחה: יש טוקן בלשונית -> ישר לאזור המנהל; אחרת מסך התחברות. */
loadOverview();

/* ===================================================================
   אן — קרדיט ומיתוג אישי בדפדפן.

   הצד הדפדפני של credit.py: אותו כיתוב, אותם קישורים, אותם אייקונים.
   דף HTML סטטי אינו יכול לקרוא מודול פייתון, וקריאת JSON הייתה מוסיפה
   בקשת רשת — והדרישה היא שהקרדיט יעבוד גם אופליין. לכן הערכים כתובים
   כאן במפורש, **ובדיקת אופליין משווה אותם מחרוזת-מחרוזת ל-credit.py**;
   כל סטייה בין השניים מפילה את סוללת הבדיקות.

   האייקונים הם SVG מוטמע — בלי CDN, בלי גופן אייקונים ובלי אף בקשת
   רשת נוספת.

   שימוש: להוסיף בעמוד <div data-anne-credit></div> (כמה שרוצים), והקובץ
   ימלא את כולם בטעינה. הוא גם מזריק את גיליון הסגנון פעם אחת.
   =================================================================== */
"use strict";

const ANNE_CREDIT = {
  authorName: "מאור דהן",
  prefix: "נבנה על ידי ",
  suffix: " במסגרת קורס AI מטעם בית הספר למנהל עסקים של האוניברסיטה העברית",
  linkedinUrl: "https://www.linkedin.com/in/maordahan/",
  githubUrl: "https://github.com/maordahan25",
  linkedinAria: "פרופיל LinkedIn של מאור דהן",
  githubAria: "פרופיל GitHub של מאור דהן",
  minTapTargetPx: 44,
  linkedinPath: "M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zM2.98 8.98h4v12h-4zM9.5 8.98h3.83v1.64h.05c.53-.95 1.83-1.96 3.77-1.96 4.03 0 4.78 2.53 4.78 5.82v6.5h-4v-5.76c0-1.37-.03-3.14-1.96-3.14-1.96 0-2.26 1.5-2.26 3.04v5.86h-4z",
  githubPath: "M12 .5C5.73.5.5 5.73.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.68 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11 11 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.12 3.05.74.81 1.18 1.84 1.18 3.1 0 4.41-2.69 5.39-5.25 5.67.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5z",
};

/* הסגנון חי כאן ולא בגיליון נפרד: כך לצד הדפדפני יש קובץ אחד, ואין
   בקשת רשת נוספת. שטח הלחיצה של כל אייקון הוא 44×44 לפחות (2.5.5),
   והמיקוד נראה — גם בעמודים שאינם טוענים את a11y.css. */
const ANNE_CREDIT_CSS = `
.anne-credit {
  direction: rtl;
  text-align: center;
  margin: 10px auto 2px;
  font-size: 0.74rem;
  line-height: 1.9;
  color: var(--text-muted, #8C7670);
}
.anne-credit a { color: var(--link, #B34A32); }
.anne-credit-name { font-weight: 600; }
.anne-credit-icons { display: inline-flex; align-items: center; vertical-align: middle; }
.anne-credit-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: ${ANNE_CREDIT.minTapTargetPx}px;
  min-height: ${ANNE_CREDIT.minTapTargetPx}px;
  color: var(--text-muted, #8C7670);
  text-decoration: none;
}
.anne-credit-icon:hover { color: var(--link, #B34A32); }
.anne-credit-icon svg { width: 17px; height: 17px; fill: currentColor; }
.anne-credit a:focus-visible {
  outline: 2px solid var(--focus-ring, #B34A32);
  outline-offset: 2px;
  border-radius: 8px;
}
@media print {
  .anne-credit { display: block !important; color: #000 !important; }
  .anne-credit a { color: #000 !important; }
}
`;

function anneCreditIcon(url, ariaLabel, pathData) {
  const link = document.createElement("a");
  link.className = "anne-credit-icon";
  link.href = url;
  link.target = "_blank";
  // אבטחה: בלי noopener הדף שנפתח מקבל window.opener ויכול לנווט
  // את החלון שלנו למקום אחר.
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", ariaLabel);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");   // השם הנגיש הוא של הקישור
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", pathData);
  svg.appendChild(path);
  link.appendChild(svg);
  return link;
}

/** בניית אלמנט הקרדיט (טקסט דרך textContent בלבד — אין innerHTML). */
function buildAnneCredit() {
  const wrap = document.createElement("p");
  wrap.className = "anne-credit";
  wrap.appendChild(document.createTextNode(ANNE_CREDIT.prefix));

  const name = document.createElement("a");
  name.className = "anne-credit-name";
  name.href = ANNE_CREDIT.linkedinUrl;
  name.target = "_blank";
  name.rel = "noopener noreferrer";
  name.textContent = ANNE_CREDIT.authorName;
  wrap.appendChild(name);

  const icons = document.createElement("span");
  icons.className = "anne-credit-icons";
  icons.appendChild(anneCreditIcon(
    ANNE_CREDIT.linkedinUrl, ANNE_CREDIT.linkedinAria, ANNE_CREDIT.linkedinPath));
  icons.appendChild(anneCreditIcon(
    ANNE_CREDIT.githubUrl, ANNE_CREDIT.githubAria, ANNE_CREDIT.githubPath));
  wrap.appendChild(icons);

  wrap.appendChild(document.createTextNode(ANNE_CREDIT.suffix));
  return wrap;
}

/** מילוי כל נקודות העגינה בעמוד (data-anne-credit) + הזרקת הסגנון. */
function mountAnneCredit(root) {
  const scope = root || document;
  if (!document.getElementById("anne-credit-style")) {
    const style = document.createElement("style");
    style.id = "anne-credit-style";
    style.textContent = ANNE_CREDIT_CSS;
    document.head.appendChild(style);
  }
  scope.querySelectorAll("[data-anne-credit]").forEach((slot) => {
    if (slot.dataset.anneCreditMounted === "1") return;
    slot.dataset.anneCreditMounted = "1";
    slot.appendChild(buildAnneCredit());
  });
}

window.anneCredit = { mount: mountAnneCredit, values: ANNE_CREDIT };

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => mountAnneCredit());
} else {
  mountAnneCredit();
}

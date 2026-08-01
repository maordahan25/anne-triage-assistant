"""
שלב Chunking.

חיתוך כל קובץ .md ליחידות משמעות לפי כותרות ## (תסמינים / טיפול ראשוני /
המשך טיפול / פנייה מיידית). כל מקטע ## הוא chunk עצמאי; מקטע ארוך מדי
מפוצל לגודל ~400-600 תווים עם חפיפה של ~50-80 תווים.

לכל chunk מצורף metadata:
    topic   - שם תת-התיקייה (wounds / anxiety / dehydration / cold)
    source  - שורת "מקור:" מתחתית הקובץ
    section - שם כותרת ה-## שאליה שייך ה-chunk
ובנוסף, לצורכי מעקב וציטוט: title (כותרת המסמך) ו-source_file (שם הקובץ).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config


@dataclass
class Chunk:
    """יחידת טקסט אחת מוכנה ל-embedding, יחד עם ה-metadata שלה."""
    text: str
    metadata: dict = field(default_factory=dict)


def _split_with_overlap(text: str,
                        max_chars: int = config.CHUNK_MAX_CHARS,
                        overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """
    פיצול טקסט ארוך לחלקים של ~max_chars עם חפיפה של ~overlap תווים.

    הפיצול שומר על שלמות שורות (הדאטה בנויה מתבליטים) — חותכים בין שורות
    ולא באמצע משפט. שורה ארוכה במיוחד מפוצלת לפי גבולות משפט.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # פירוק ליחידות אטומיות: שורות; שורה ארוכה מדי -> משפטים
    units: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(line) <= max_chars:
            units.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line)
        buf = ""
        for s in sentences:
            if buf and len(buf) + len(s) + 1 > max_chars:
                units.append(buf)
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            units.append(buf)

    # אריזה חמדנית של יחידות ל-chunks, עם חפיפה בקצה
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for unit in units:
        addition = len(unit) + (1 if cur else 0)
        if cur and cur_len + addition > max_chars:
            chunks.append("\n".join(cur))
            # בניית "זנב" חופף מהשורות האחרונות (~overlap תווים)
            tail: list[str] = []
            tail_len = 0
            for u in reversed(cur):
                if tail and tail_len + len(u) + 1 > overlap:
                    break
                tail.insert(0, u)
                tail_len += len(u) + 1
            cur = list(tail)
            cur_len = sum(len(u) + 1 for u in cur)
        cur.append(unit)
        cur_len += len(unit) + 1

    if cur:
        chunks.append("\n".join(cur))
    return chunks


def _extract_source(body: str) -> str:
    """חילוץ שורת המקור מתחתית הקובץ (השורה שמתחילה ב-'מקור:')."""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("מקור:"):
            return line[len("מקור:"):].strip()
    return ""


def _extract_title(body: str) -> str:
    """חילוץ כותרת המסמך (שורת '# ' הראשונה)."""
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return ""


def _split_sections(body: str) -> list[tuple[str, str]]:
    """
    פיצול גוף המסמך למקטעים לפי כותרות ##.
    מחזיר רשימת (שם_כותרת, טקסט_המקטע). ה-footer שאחרי '---' אינו נכלל.
    """
    # ניתוק ה-footer (מקור/הערה) המופיע אחרי קו '---'
    main = re.split(r"\n-{3,}\s*\n", body, maxsplit=1)[0]

    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in main.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[3:].strip()
            current_lines = []
        elif current_title is not None:
            current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))
    return sections


def chunk_file(path: Path, topic: str) -> list[Chunk]:
    """חיתוך קובץ .md בודד לרשימת Chunks עם metadata."""
    body = path.read_text(encoding="utf-8")
    title = _extract_title(body)
    source = _extract_source(body)

    chunks: list[Chunk] = []
    for section, section_text in _split_sections(body):
        if not section_text:
            continue
        for part in _split_with_overlap(section_text):
            chunks.append(Chunk(
                text=part,
                metadata={
                    "topic": topic,
                    "section": section,
                    "source": source,
                    "title": title,
                    "source_file": path.name,
                },
            ))
    return chunks


def load_chunks(data_dir: Path = config.DATA_DIR) -> list[Chunk]:
    """
    טעינת כל קבצי ה-.md מתחת ל-data/ וחיתוכם ל-chunks.
    שם תת-התיקייה משמש כתגית ה-topic.
    """
    all_chunks: list[Chunk] = []
    for topic_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        topic = topic_dir.name
        for md_file in sorted(topic_dir.glob("*.md")):
            all_chunks.extend(chunk_file(md_file, topic))
    return all_chunks


if __name__ == "__main__":
    # הרצה ישירה: תצוגה מקדימה של ה-chunks שנוצרו (לבדיקה ידנית).
    chunks = load_chunks()
    print(f"נוצרו {len(chunks)} chunks מתוך הדאטה.\n")
    for i, ch in enumerate(chunks[:5]):
        m = ch.metadata
        print(f"[{i}] topic={m['topic']} | section={m['section']} | file={m['source_file']}")
        print(f"    אורך: {len(ch.text)} תווים")
        print(f"    {ch.text[:120].replace(chr(10), ' ')}...\n")

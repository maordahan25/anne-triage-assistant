"""
הגדרות מרכזיות לצינור ה-RAG (שלב א': chunking → embeddings → אחסון).
ריכוז כל הפרמטרים במקום אחד כדי שיהיה קל לכייל ולהרחיב בהמשך.
"""
from pathlib import Path

# --- נתיבים ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"          # תיקיית הדאטה (תת-תיקייה לכל topic)
CHROMA_DIR = PROJECT_ROOT / "chroma_db"   # אחסון מתמיד של ה-Vector DB על הדיסק

# --- Vector DB ---
COLLECTION_NAME = "anne_first_aid"
DISTANCE_METRIC = "cosine"                 # e5 מנורמל ל-cosine similarity

# --- מודל ה-Embedding ---
# מודל מולטי-לינגואלי מקומי המתאים היטב לעברית, חינמי וללא צורך ב-API key.
# משפחת e5 דורשת קידומות: "passage: " למסמכים ו-"query: " לשאילתות.
EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

# --- פרמטרים של Chunking (לפי שקף 6 במצגת) ---
CHUNK_MAX_CHARS = 600     # גודל מקסימלי לרכיב טקסט בודד
CHUNK_OVERLAP = 70        # חפיפה בין chunks עוקבים (~50-80 תווים)

# --- שליפה ---
DEFAULT_TOP_K = 4

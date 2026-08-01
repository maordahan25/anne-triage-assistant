"""
נקודת כניסה לבניית ה-Vector DB.

הרצה:
    python build_index.py

מריץ את הצינור המלא: chunking -> embeddings -> אחסון ב-Chroma.
"""
from rag.embedding_store import build_index

if __name__ == "__main__":
    build_index()

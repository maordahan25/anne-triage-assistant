"""
שלב Embeddings + אחסון ב-Vector DB.

- Embedder: עוטף מודל מולטי-לינגואלי (multilingual-e5) להמרת טקסט לוקטורים.
- VectorStore: עוטף Chroma (מתמיד על הדיסק) לאחסון ושליפה סמנטית.
- build_index(): מריץ את הצינור המלא — chunking -> embedding -> אחסון.

הערה על e5: המודל דורש קידומות שונות למסמכים ולשאילתות
("passage: " מול "query: ") לקבלת איכות שליפה מיטבית בעברית.
"""
from __future__ import annotations

import shutil

import chromadb
from sentence_transformers import SentenceTransformer

from . import config
from .chunking import Chunk, load_chunks


class Embedder:
    """המרת טקסט לוקטורים באמצעות מודל e5 מקומי."""

    def __init__(self, model_name: str = config.EMBEDDING_MODEL):
        self.model = SentenceTransformer(model_name)

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        prefixed = [config.PASSAGE_PREFIX + t for t in texts]
        vectors = self.model.encode(prefixed, normalize_embeddings=True,
                                    show_progress_bar=True)
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = self.model.encode(config.QUERY_PREFIX + text,
                                   normalize_embeddings=True)
        return vector.tolist()


class VectorStore:
    """עטיפה דקה ל-Chroma persistent client."""

    def __init__(self,
                 path=config.CHROMA_DIR,
                 collection_name: str = config.COLLECTION_NAME):
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": config.DISTANCE_METRIC},
        )

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        ids = [f"chunk-{i}" for i in range(len(chunks))]
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[c.metadata for c in chunks],
        )

    def query(self, query_embedding: list[float], top_k: int = config.DEFAULT_TOP_K,
              topic: str | None = None) -> list[dict]:
        """שליפת ה-top_k הקרובים ביותר, עם אפשרות לסינון לפי topic."""
        where = {"topic": topic} if topic else None
        res = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
        )
        results: list[dict] = []
        for doc, meta, dist in zip(res["documents"][0],
                                   res["metadatas"][0],
                                   res["distances"][0]):
            results.append({
                "text": doc,
                "metadata": meta,
                "similarity": 1 - dist,  # cosine distance -> similarity
            })
        return results


def build_index(reset: bool = True) -> int:
    """
    בניית האינדקס מאפס: טעינה -> chunking -> embedding -> אחסון ב-Chroma.
    מחזיר את מספר ה-chunks שנאגרו.
    """
    if reset and config.CHROMA_DIR.exists():
        print(f"מוחק אינדקס קיים: {config.CHROMA_DIR}")
        shutil.rmtree(config.CHROMA_DIR)

    print("1/3  טוען וחותך מסמכים...")
    chunks = load_chunks()
    print(f"     נוצרו {len(chunks)} chunks.")

    print(f"2/3  מחשב embeddings עם '{config.EMBEDDING_MODEL}'...")
    embedder = Embedder()
    embeddings = embedder.embed_passages([c.text for c in chunks])

    print("3/3  שומר ב-Chroma Vector DB...")
    store = VectorStore()
    store.add(chunks, embeddings)
    print(f"הסתיים. {len(chunks)} chunks נשמרו ב-{config.CHROMA_DIR}")
    return len(chunks)


def search(query: str, top_k: int = config.DEFAULT_TOP_K,
           topic: str | None = None) -> list[dict]:
    """שליפה סמנטית: ממיר שאילתה לוקטור ומחזיר את ה-chunks הקרובים."""
    embedder = Embedder()
    store = VectorStore()
    return store.query(embedder.embed_query(query), top_k=top_k, topic=topic)


if __name__ == "__main__":
    build_index()

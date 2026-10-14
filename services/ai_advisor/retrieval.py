"""Lightweight retrieval (the "R" in RAG) over the maintenance knowledge base.

TF-IDF is enough for a small, curated knowledge base and needs no GPU or extra
service. For a large document set, swap this for embeddings + a vector store
(e.g. pgvector inside the same TimescaleDB) without changing the advisor.
"""
import re
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Translate model features into the vocabulary maintenance engineers use
FEATURE_PHRASES = {
    "duty_loaded": "compressor duty cycle loaded runs longer more time under load",
    "load_cycles": "more frequent load cycles compressor starts",
    "reservoirs": "reservoir pressure drop",
    "tp2": "compressor outlet pressure TP2",
    "tp3": "pneumatic panel pressure TP3",
    "h1": "H1 cyclonic separator filter pressure",
    "dv_pressure": "DV pressure dryer tower discharge",
    "oil_temperature": "oil temperature high cooling",
    "motor_current": "motor current",
}


class KnowledgeBase:
    def __init__(self, folder: Path):
        self.chunks: list[dict] = []
        for path in sorted(folder.glob("*.md")):
            for part in re.split(r"\n(?=## )", path.read_text(encoding="utf-8")):
                if part.startswith("## "):
                    title = part.splitlines()[0][3:].strip()
                    self.chunks.append({"source": path.name, "title": title, "text": part.strip()})
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self.matrix = self.vectorizer.fit_transform([c["text"] for c in self.chunks])

    def search(self, query: str, k: int = 2) -> list[dict]:
        sims = cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]
        best = sims.argsort()[::-1][:k]
        return [{**self.chunks[i], "score": round(float(sims[i]), 3)} for i in best if sims[i] > 0]


def query_from_contributors(contributors: list[dict]) -> str:
    parts = []
    for c in contributors or []:
        feature, direction = c.get("feature", ""), c.get("direction", "")
        key = feature if feature in FEATURE_PHRASES else c.get("sensor", "")
        phrase = FEATURE_PHRASES.get(key, feature.replace("_", " "))
        word = "high above baseline increased" if direction == "above" else "low below baseline drop"
        parts.append(f"{phrase} {word}")
    return " ".join(parts)


def section_field(text: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""

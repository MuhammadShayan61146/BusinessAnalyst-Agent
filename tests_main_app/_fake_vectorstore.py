"""

It persists its state to a JSON file under persist_directory, so a
"reopen the same store" test is meaningful (a second FakeVectorStore
pointed at the same directory actually sees the first one's data)
rather than trivially true.

"""
import json
import os
from types import SimpleNamespace


class FakeVectorStore:
    def __init__(self, persist_directory, collection_name="knowledge_base"):
        self.persist_directory = persist_directory
        os.makedirs(persist_directory, exist_ok=True)
        self.path = os.path.join(persist_directory, f"_fake_store_{collection_name}.json")
        self._data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                return json.load(f)
        return {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._data, f)

    def add_texts(self, texts, metadatas, ids):
        for text, meta, id_ in zip(texts, metadatas, ids):
            self._data[id_] = {"text": text, "metadata": meta}
        self._save()
        return list(ids)

    def delete(self, ids):
        for id_ in ids:
            self._data.pop(id_, None)
        self._save()

    def similarity_search_with_relevance_scores(self, query, k):
        query_tokens = set(query.lower().split())
        scored = []
        for entry in self._data.values():
            doc_tokens = set(entry["text"].lower().split())
            overlap = len(query_tokens & doc_tokens)
            score = overlap / max(len(query_tokens), 1)
            scored.append((entry, score))
        scored.sort(key=lambda t: t[1], reverse=True)
        out = []
        for entry, score in scored[:k]:
            doc = SimpleNamespace(page_content=entry["text"], metadata=entry["metadata"])
            out.append((doc, score))
        return out

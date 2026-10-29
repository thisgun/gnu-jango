"""A deterministic, offline embedding provider for tests and local demos.

Each word (after ``synonyms`` mapping) adds weight to one hashed dimension, so texts that share a
word, or a synonym of one, are similar and unrelated texts are near orthogonal. No network.
"""
import hashlib
import re

_WORD = re.compile(r"\w+", re.UNICODE)


class FakeEmbeddingProvider:
    def __init__(self, *, synonyms=None, dimensions=1024, model="fake-embedding", batch_size=2, error=None):
        self.synonyms = {key.lower(): value.lower() for key, value in (synonyms or {}).items()}
        self.dimensions = dimensions
        self.model = model
        self.batch_size = batch_size
        self.error = error
        self.calls = []

    def vector(self, text):
        values = [0.0] * self.dimensions
        for word in _WORD.findall(str(text or "").lower()):
            concept = self.synonyms.get(word, word)
            index = int(hashlib.sha256(concept.encode("utf-8")).hexdigest()[:8], 16) % self.dimensions
            values[index] += 1.0
        if not any(values):
            values[0] = 1.0
        return values

    def embed(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        if self.error is not None:
            raise self.error
        return [self.vector(text) for text in texts]

    @property
    def embedded_texts(self):
        return [text for batch in self.calls for text in batch]

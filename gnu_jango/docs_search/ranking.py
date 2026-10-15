from collections import Counter
from math import log


def bm25_scores(documents, query_terms, *, k1=1.5, b=0.75):
    """Small Okapi BM25 implementation; documents are already tokenized and field-weighted."""
    size = len(documents)
    if not size or not query_terms:
        return [0.0] * size
    lengths = [len(document) for document in documents]
    average = sum(lengths) / size or 1.0
    frequencies = [Counter(document) for document in documents]
    document_frequency = Counter(term for document in frequencies for term in document)
    scores = []
    for index, terms in enumerate(frequencies):
        score = 0.0
        normalizer = k1 * (1 - b + b * lengths[index] / average)
        for term in set(query_terms):
            count = terms.get(term, 0)
            if count:
                df = document_frequency[term]
                inverse = log(1 + (size - df + 0.5) / (df + 0.5))
                score += inverse * count * (k1 + 1) / (count + normalizer)
        scores.append(score)
    return scores

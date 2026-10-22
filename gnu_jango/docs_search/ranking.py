from collections import Counter
from math import log


def bm25_scores(documents, query_terms, *, k1=1.5, b=0.75, prefixes=()):
    """Small Okapi BM25 implementation; documents are already tokenized and field-weighted."""
    lengths = [len(document) for document in documents]
    frequencies = [Counter(document) for document in documents]
    for frequency in frequencies:
        # Read the original frequencies so overlapping prefixes never double
        # count synthetic prefix entries. Length normalization stays unchanged.
        original = tuple(frequency.items()) if prefixes else ()
        for prefix in prefixes:
            count = sum(count for token, count in original if token.startswith(prefix))
            if count:
                frequency[prefix] = count
    return bm25_from_stats(frequencies, lengths, query_terms, k1=k1, b=b)


def bm25_from_stats(frequencies, lengths, query_terms, *, k1=1.5, b=0.75):
    """Equivalent BM25 from bounded query frequencies and original token lengths."""
    size = len(frequencies)
    if not size or not query_terms:
        return [0.0] * size
    average = sum(lengths) / size or 1.0
    document_frequency = Counter(term for document in frequencies for term, count in document.items() if count)
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

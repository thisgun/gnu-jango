"""Near-duplicate text detection by character 3-gram shingles and Jaccard similarity.

Comparing every pair of n texts costs n^2 set intersections. Here each text keeps only the
rarest ``len - ceil(t * len) + 1`` of its shingles in an inverted index (the prefix filter): two
sets with Jaccard >= t always share one of those, so only texts that meet in the index are
compared exactly.
"""

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

SHINGLE_SIZE = 3
_DROPPED = re.compile(r"[\W_]+")


def normalise(text):
    """NFKC-folded, lower-cased text without spaces and punctuation, so spacing and Unicode-form
    tricks (decomposed Hangul, full-width letters) do not hide a copy."""
    return _DROPPED.sub("", unicodedata.normalize("NFKC", text or "").lower())


def shingles(text, size=SHINGLE_SIZE):
    flat = normalise(text)
    return frozenset(flat[i : i + size] for i in range(len(flat) - size + 1))


def jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@dataclass(frozen=True)
class SimilarPair:
    left: int
    right: int
    similarity: float


@dataclass(frozen=True)
class SimilarityResult:
    pairs: tuple
    candidates: int


def similar_pairs(texts, threshold=0.8, min_length=20, allow_pair=None):
    """Index pairs of ``texts`` with Jaccard >= ``threshold``, both texts at least ``min_length``
    characters once normalised. ``allow_pair(i, j)`` can veto a pair (for example, the same author)
    before the exact comparison. ``candidates`` counts the exact comparisons made."""
    sets = {}
    for index, text in enumerate(texts):
        if len(normalise(text)) >= min_length:
            sets[index] = shingles(text)
    frequency = Counter(token for tokens in sets.values() for token in tokens)
    ordered = {index: sorted(tokens, key=lambda token: (frequency[token], token)) for index, tokens in sets.items()}

    index_of = defaultdict(list)
    pairs = []
    candidates = 0
    for index in sorted(ordered):
        tokens = ordered[index]
        size = len(tokens)
        prefix = tokens[: size - math.ceil(threshold * size) + 1]
        seen = set()
        for token in prefix:
            for other in index_of[token]:
                if other in seen:
                    continue
                seen.add(other)
                other_size = len(sets[other])
                if other_size < threshold * size or size < threshold * other_size:
                    continue
                if allow_pair is not None and not allow_pair(other, index):
                    continue
                candidates += 1
                similarity = jaccard(sets[other], sets[index])
                if similarity >= threshold:
                    pairs.append(SimilarPair(other, index, similarity))
            index_of[token].append(index)
    return SimilarityResult(tuple(pairs), candidates)


def clusters(pairs):
    """Connected groups of indexes joined by ``pairs``, as sorted tuples, largest first."""
    parent = {}

    def find(item):
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for pair in pairs:
        parent[find(pair.left)] = find(pair.right)
    groups = defaultdict(list)
    for item in list(parent):
        groups[find(item)].append(item)
    return sorted((tuple(sorted(group)) for group in groups.values()), key=lambda group: (-len(group), group))

import re
from collections import Counter

_WORD_PATTERN = re.compile(r"[a-z0-9']+")

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "so", "to", "of", "in", "on",
    "at", "by", "for", "with", "about", "as", "is", "it", "its", "this",
    "that", "these", "those", "i", "you", "he", "she", "we", "they", "them",
    "my", "your", "our", "their", "be", "was", "were", "are", "am", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "can", "could", "shall", "should", "may", "might", "must", "not", "no",
    "yes", "just", "like", "get", "got", "go", "going", "one", "up", "out",
    "there", "here", "what", "when", "where", "how", "all", "some", "into",
}

_TIMESTAMP_PATTERN = re.compile(r"^\[\d{2}:\d{2}\]\s*")


def _clean_words(text: str) -> list[str]:
    text = _TIMESTAMP_PATTERN.sub("", text)
    return [w for w in _WORD_PATTERN.findall(text.lower()) if w not in _STOPWORDS and len(w) > 1]


def top_ngrams(text: str, n: int, top_k: int = 15) -> list[tuple[str, int]]:
    """Top n-word phrases by frequency, stripped of timestamps and stopwords.
    n=1 is single keywords, n=2/3 are the more useful SEO-relevant phrases."""
    words = _clean_words(text)
    if len(words) < n:
        return []
    phrases = [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]
    return Counter(phrases).most_common(top_k)

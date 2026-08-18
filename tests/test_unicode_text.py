"""Non-Latin text handling across the extraction path.

The app hardcodes autocomplete's region to IN (autocomplete.DEFAULT_REGION)
and its own code comments target Indian creators, yet every tokenizer here
was ASCII-only until these tests existed. These lock the fix in place.
"""

import re
import unicodedata

import pytest

from keyword_pipeline import build_seeds
from keyword_rank import _content_words, content_coverage
from keywords import _COMBINING_MARKS, _WORD_PATTERN, _clean_words, top_ngrams

HINDI_TRANSCRIPT = (
    "[00:00] आज हम जर्मनी के APS सर्टिफिकेट की बात करेंगे\n"
    "[00:05] APS सर्टिफिकेट भारतीय छात्रों के लिए ज़रूरी है\n"
    "[00:10] जर्मनी के विश्वविद्यालय में admission के लिए APS सर्टिफिकेट चाहिए"
)


# ------------------------------------------------------------- tokenization


@pytest.mark.parametrize("word", [
    "जर्मनी", "विश्वविद्यालय", "छात्रों", "ज़रूरी", "सर्टिफिकेट",  # Devanagari
    "தமிழ்", "বাংলা", "ਪੰਜਾਬੀ", "ગુજરાતી", "ಕನ್ನಡ", "മലയാളം", "తెలుగు", "සිංහල",
    "العربية", "עברית", "café", "Ñoño", "don't", "it’s", "APS", "2024",
])
def test_word_survives_tokenization_whole(word):
    """One word in, one token out. The pre-fix failure was not that Indic
    text was dropped -- it is that `\\w+` SPLITS it at every combining mark,
    turning "जर्मनी" into ["जर", "मन"]: fake words that look real."""
    assert _WORD_PATTERN.findall(word) == [word]


def test_naive_word_class_would_shatter_indic_text():
    """Guards the reason the pattern is written the way it is -- if someone
    'simplifies' it back to \\w+, this fails loudly."""
    assert re.findall(r"\w+", "जर्मनी") == ["जर", "मन"]
    assert _WORD_PATTERN.findall("जर्मनी") == ["जर्मनी"]


def test_punctuation_and_danda_are_not_swallowed():
    assert _WORD_PATTERN.findall("जर्मनी में, APS ज़रूरी है। सही?") == [
        "जर्मनी", "में", "APS", "ज़रूरी", "है", "सही",
    ]


def test_mark_ranges_cover_every_indic_mark():
    """_COMBINING_MARKS is generated, so this regenerates and compares rather
    than trusting the checked-in literal."""
    uncovered = [
        hex(c) for c in range(0x900, 0xE80)
        if unicodedata.category(chr(c)) in ("Mn", "Mc", "Me")
        and not re.match("[" + _COMBINING_MARKS + "]", chr(c))
    ]
    assert uncovered == []


# ------------------------------------------------------------------ n-grams


def test_devanagari_transcript_yields_its_real_subject():
    bigrams = dict(top_ngrams(HINDI_TRANSCRIPT, 2, 6))
    assert "aps सर्टिफिकेट" in bigrams
    assert bigrams["aps सर्टिफिकेट"] == 3


def test_timestamps_never_become_keywords():
    """Regression: digits from "[00:05]" must not survive as tokens."""
    assert not [w for w in _clean_words(HINDI_TRANSCRIPT) if w.isdigit()]


def test_hindi_function_words_are_filtered():
    tokens = _clean_words(HINDI_TRANSCRIPT)
    assert "के" not in tokens
    assert "है" not in tokens
    assert "जर्मनी" in tokens


def test_romanized_hinglish_stopwords_are_filtered():
    """Live bug independent of Unicode: Hinglish written in Latin script
    passed the English stopword list untouched, so "ke liye" outranked the
    video's actual subject."""
    roman = (
        "aps certificate ke liye kya karna hai. germany ke universities mein "
        "admission ke liye aps certificate chahiye hota hai"
    )
    bigrams = dict(top_ngrams(roman, 2, 8))
    assert "ke liye" not in bigrams
    assert "aps certificate" in bigrams
    assert max(bigrams, key=bigrams.get) == "aps certificate"


# ----------------------------------------------------------------- coverage


def test_devanagari_keyword_gets_real_coverage():
    """Pre-fix this returned 0.0 -- a Hindi video reported as not covering
    its own stated subject."""
    coverage = content_coverage(
        "जर्मनी विश्वविद्यालय", "जर्मनी के विश्वविद्यालय", "", None, None
    )
    assert coverage > 0


def test_content_words_extracted_from_devanagari():
    assert _content_words("जर्मनी विश्वविद्यालय") == ["जर्मनी", "विश्वविद्यालय"]


def test_uncovered_devanagari_keyword_still_scores_zero():
    """The fix must not make everything score non-zero -- an unrelated
    keyword still has to come back uncovered."""
    assert content_coverage("तमिल संगीत", "जर्मनी के विश्वविद्यालय", "", None, None) == 0.0


# -------------------------------------------------------------------- seeds


def test_hindi_title_produces_seeds():
    """Devanagari is unicameral, so the capitalised-run entity detector finds
    nothing and the title-bigram fallback is the only source left."""
    seeds = build_seeds("", "जर्मनी में APS सर्टिफिकेट कैसे बनाएं", None, None)
    assert seeds
    assert "जर्मनी सर्टिफिकेट" in seeds


def test_hindi_question_scaffolding_is_not_a_seed():
    seeds = build_seeds("", "जर्मनी में APS सर्टिफिकेट कैसे बनाएं", None, None)
    assert not any("कैसे" in s or "बनाएं" in s for s in seeds)


def test_english_behaviour_is_unchanged():
    """The whole fix is additive -- Latin-script extraction must be
    byte-identical to before."""
    text = "the aps certificate is required for indian students in germany"
    assert dict(top_ngrams(text, 2, 3))["aps certificate"] == 1
    assert _content_words("aps certificate germany") == [
        "aps", "certificate", "germany",
    ]

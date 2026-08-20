"""Morphological matching in the relevance and coverage paths.

The bug these lock down, measured on a realistic candidate pool: a plural
variant of the right keyword scored 0.144 against its singular's 0.262 --
below RELEVANCE_FLOOR -- so the same keyword survived or was deleted
depending only on its grammatical number.
"""

import pytest

from candidates import Candidate, build_pool, score_relevance
from keyword_rank import _content_words, content_coverage
from keywords import _clean_words, stem, stem_words, top_ngrams, top_ngrams_by_stem


@pytest.mark.parametrize("singular,plural", [
    ("certificate", "certificates"),
    ("university", "universities"),
    ("student", "students"),
    ("scholarship", "scholarships"),
    ("document", "documents"),
    ("box", "boxes"),
    ("class", "classes"),
    ("dish", "dishes"),
])
def test_singular_and_plural_share_a_stem(singular, plural):
    assert stem(singular) == stem(plural)


def test_es_is_only_stripped_after_a_sibilant():
    """Regression for a bug this shipped with once: treating "-es" as a
    suffix unconditionally turned "certificates" into "certificat" while
    "certificate" stemmed to itself, so the pair stopped matching -- the
    exact failure stemming was added to fix."""
    assert stem("certificates") == "certificate"
    assert stem("boxes") == "box"


@pytest.mark.parametrize("word", [
    "process", "address", "class",      # -ss must never be stripped
    "aps", "gas", "bus", "news",        # too short, or only look plural
    "germany", "jinnah", "2024",
    "जर्मनी", "தமிழ்",                    # non-Latin: no English morphology
])
def test_words_that_must_not_be_stemmed(word):
    assert stem(word) == word


def test_short_acronyms_are_protected_by_the_length_guard():
    assert stem("aps") == "aps"
    assert stem("gre") == "gre"


def test_over_stemmed_acronym_still_matches_because_stemming_is_symmetric():
    """"ielts" does stem to "ielt" -- the -s rule cannot tell an acronym from
    a plural once the text is lowercased. That is acceptable, and this test
    pins down WHY, so nobody "fixes" it by adding an acronym allowlist: both
    sides of every comparison run through the same function, so the pair
    still matches, and stems never reach the user (see the surface-form
    tests above). Over-stemming is only dangerous if it collides with a
    different real word, which "ielt" does not."""
    assert stem_words("ielts band 7") == ["ielt", "band"]
    assert stem_words("IELTS preparation for band 7") == ["ielt", "preparation", "band"]

    pool = build_pool(["ielts band 7"], [], [])
    score_relevance(pool, "IELTS preparation guide for band 7 speaking")
    assert pool[0].relevance > 0.3

    assert "ielts band" in [p for p, _ in top_ngrams("ielts band 7 speaking", 2, 5)]


# --------------------------------------------------- stemming stays internal


def test_extraction_keeps_surface_forms():
    """Users read n-grams. Stemming must not reach them, or the report would
    recommend "aps certificat" as a tag."""
    text = "aps certificates for indian students applying to german universities"
    phrases = [p for p, _ in top_ngrams(text, 2, 10)]
    assert "aps certificates" in phrases
    assert not any("certificat " in p or p.endswith("certificat") for p in phrases)


def test_clean_words_is_unstemmed_and_stem_words_is_stemmed():
    text = "german universities"
    assert _clean_words(text) == ["german", "universities"]
    assert stem_words(text) == ["german", "university"]


# ------------------------------------------------------------ scoring effect


def test_plural_variant_scores_like_its_singular():
    """Built directly rather than through build_pool, which now collapses
    these two into one candidate (see test_dedup.py). The property under test
    here is the scoring parity that makes that collapse safe."""
    singular = Candidate(phrase="aps certificate germany")
    plural = Candidate(phrase="aps certificates germany")
    score_relevance(
        [singular, plural], "The APS certificate process for German universities."
    )
    assert singular.relevance == pytest.approx(plural.relevance, abs=1e-9)


def test_coverage_matches_across_plurality():
    """"university" in the keyword vs "universities" in the description used
    to score zero overlap on that word."""
    assert content_coverage(
        "german university admission", "Admission to German universities", "", None, None
    ) > 0


def test_content_words_are_stemmed_for_matching():
    assert _content_words("german universities") == ["german", "university"]


def test_overlap_no_longer_matches_on_bare_prefixes():
    """The old `\\b{word}` regex counted any word STARTING with the keyword's
    word, so "germ" was scored as covering "germany"."""
    assert content_coverage("germ", "germany travel guide", "", None, None) == 0.0


def test_unrelated_keyword_still_scores_zero_coverage():
    assert content_coverage("tamil music", "german university admission", "", None, None) == 0.0


# ------------------------------------------------------- iterative stemming
#
# stem() originally applied one suffix rule and stopped. "rankings" ->
# strip "-s" -> "ranking" -> STOP, never re-checking that "ranking" itself
# still had a strippable "-ing". Called directly, "ranking" stripped straight
# to "rank" -- so the plural and singular of the same word landed on
# different stems and silently failed to match. Found while building
# top_ngrams_by_stem, not invented in the abstract.


def test_multi_suffix_word_reaches_the_same_stem_either_form():
    assert stem("ranking") == stem("rankings") == "rank"


@pytest.mark.parametrize("word,expected", [
    ("rankings", "rank"),
    ("rankings", stem("ranking")),  # the two must agree with EACH OTHER, not just a hardcoded value
])
def test_rankings_matches_ranking_exactly(word, expected):
    assert stem(word) == expected


def test_stemming_is_bounded_not_unlimited():
    """Guards the fix's own safety valve: chaining strips indefinitely could
    over-strip a short, unrelated word past recognition. Two passes is the
    documented ceiling -- this should not, for instance, strip all the way
    down to a 1-2 letter fragment."""
    assert len(stem("rankings")) >= 3


# --------------------------------------------------- top_ngrams_by_stem


def test_morphological_variants_merge_into_one_occurrence():
    """The real bug this exists to fix: a supply-lane repeat-count gate saw
    "masters degree" and "masters degrees" as two different phrases said
    once each, instead of one topic said twice."""
    text = "this masters degree program is popular. many masters degrees are offered here."
    merged = dict(top_ngrams_by_stem(text, 2, 10))
    assert merged.get("masters degree") == 2


def test_top_ngrams_by_stem_word_order_still_matters():
    """Only word FORM is normalized, not word order -- "study abroad" and
    "abroad study" are different phrases and must not be merged."""
    text = "study abroad is popular. abroad study takes planning."
    merged = dict(top_ngrams_by_stem(text, 2, 10))
    assert merged.get("study abroad") == 1
    assert merged.get("abroad study") == 1


def test_top_ngrams_by_stem_keeps_the_dominant_surface_form():
    """The representative phrasing shown is whichever variant the creator
    actually said most -- never invented wording."""
    text = "university ranking matters. university ranking helps. university rankings vary."
    merged = dict(top_ngrams_by_stem(text, 2, 10))
    assert merged.get("university ranking") == 3
    assert "university rankings" not in merged


def test_top_ngrams_stays_literal_for_the_density_chart():
    """top_ngrams itself (used by app.py's raw "Keyword density" chart) must
    NOT change behaviour -- only the new function merges."""
    text = "masters degree program. masters degrees available."
    literal = dict(top_ngrams(text, 2, 10))
    assert literal.get("masters degree") == 1
    assert literal.get("masters degrees") == 1

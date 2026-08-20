"""Graph's own relevance ranking handles full natural-language questions
well (confirmed against real content — see graph.py's _build_kql_query
docstring for what changed and why); this just guards against
regressing back to the stopword-stripping/OR-joining that turned out to
hurt results rather than help them."""
from backend.services.graph import _build_kql_query


def test_passes_question_through_unchanged():
    question = "What date was the last site in Tullylost done?"
    assert _build_kql_query(question) == question


def test_trims_surrounding_whitespace():
    assert _build_kql_query("  confined space PPE  ") == "confined space PPE"


def test_does_not_strip_stopwords_or_inject_or():
    # Regression guard: an earlier version stripped words like "how",
    # "many", "the" and joined the rest with " OR ", which discarded
    # phrase context Graph's own ranking otherwise uses well.
    question = "How many sites are in the UE PCV Survey folder?"
    result = _build_kql_query(question)
    assert result == question
    assert " OR " not in result

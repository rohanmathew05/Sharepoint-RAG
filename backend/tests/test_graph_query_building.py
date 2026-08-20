"""Verifies natural-language questions get turned into a Graph/KQL query
that actually has a chance of matching real documents, instead of being
sent verbatim (which defaults to AND-ing every word in the sentence)."""
from backend.services.graph import _build_kql_query


def test_strips_stopwords_and_ors_remaining_keywords():
    result = _build_kql_query("What date was the last site in Tullylost done?")
    assert result == "date OR site OR Tullylost"


def test_ors_keywords_with_or_keyword():
    result = _build_kql_query("What are the coordinates for Neilstown Community Centre?")
    assert " OR " in result
    for keyword in ["coordinates", "Neilstown", "Community", "Centre"]:
        assert keyword in result


def test_falls_back_to_original_question_if_all_stopwords():
    result = _build_kql_query("What is this and that?")
    assert result == "What is this and that?"


def test_no_and_semantics_leak_through():
    # KQL treats bare space-separated terms as AND by default — every
    # remaining keyword must be joined with an explicit OR so a document
    # only needs to match one of them, not all.
    result = _build_kql_query("confined space PPE requirements")
    assert result == "confined OR space OR PPE OR requirements"

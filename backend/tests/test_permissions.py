"""Demonstrates the core security requirement: retrieval results differ by
user according to actual SharePoint group membership, and a user without
access to a group never receives its documents — regardless of query."""
import pytest

from backend.services.demo_data import search_demo_documents

USER_A = "00000000-0000-0000-0000-0000000000a1"  # General + Health & Safety
USER_B = "00000000-0000-0000-0000-0000000000b1"  # General + Health & Safety + Engineering


def test_user_a_cannot_see_engineering_docs():
    results = search_demo_documents(USER_A, "pump specifications installation", size=10)
    assert results == []


def test_user_b_can_see_engineering_docs():
    results = search_demo_documents(USER_B, "pump specifications installation", size=10)
    names = {doc.document_name for doc in results}
    assert "Pump Specifications.pdf" in names
    assert "Installation Guide.pdf" in names


def test_neither_demo_user_can_see_hr_docs():
    for user in (USER_A, USER_B):
        results = search_demo_documents(user, "salary bands annual leave accrual", size=10)
        assert results == []


def test_both_users_can_see_shared_health_and_safety_docs():
    for user in (USER_A, USER_B):
        results = search_demo_documents(user, "confined space PPE", size=10)
        names = {doc.document_name for doc in results}
        assert "Confined Space Policy.pdf" in names
        assert "PPE Requirements.docx" in names


def test_unknown_user_sees_nothing():
    results = search_demo_documents("unknown-user-oid", "confined space", size=10)
    assert results == []


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_still_respects_permissions(query):
    # An empty query must not become a bypass that dumps every document.
    results = search_demo_documents(USER_A, query, size=100)
    names = {doc.document_name for doc in results}
    assert "Salary Policy.pdf" not in names
    assert "Pump Specifications.pdf" not in names

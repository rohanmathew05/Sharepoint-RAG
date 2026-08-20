"""Citation links should open the file in SharePoint's browser viewer,
not trigger a download / hand off to a desktop Office app."""
from backend.services.url_utils import as_browser_viewable_url


def test_appends_web_param_when_no_query_string():
    url = "https://contoso.sharepoint.com/sites/intranet/Shared%20Documents/Policy.pdf"
    assert as_browser_viewable_url(url) == url + "?web=1"


def test_appends_web_param_after_existing_query_string():
    url = "https://contoso.sharepoint.com/sites/intranet/Shared%20Documents/Policy.pdf?d=abc123"
    assert as_browser_viewable_url(url) == url + "&web=1"


def test_empty_url_passes_through_unchanged():
    assert as_browser_viewable_url("") == ""

"""Citation links should open the file in SharePoint's browser viewer,
not trigger a download / hand off to a desktop Office app."""
from backend.services.url_utils import as_browser_viewable_url, folder_path_from_web_url


def test_appends_web_param_when_no_query_string():
    url = "https://contoso.sharepoint.com/sites/intranet/Shared%20Documents/Policy.pdf"
    assert as_browser_viewable_url(url) == url + "?web=1"


def test_appends_web_param_after_existing_query_string():
    url = "https://contoso.sharepoint.com/sites/intranet/Shared%20Documents/Policy.pdf?d=abc123"
    assert as_browser_viewable_url(url) == url + "&web=1"


def test_empty_url_passes_through_unchanged():
    assert as_browser_viewable_url("") == ""


def test_folder_path_for_file_excludes_its_own_filename():
    url = (
        "https://contoso.sharepoint.com/Shared Documents/WATER CONTROL SHARED FOLDER"
        "/UE PCV SURVEY/KILDARE/WFV0002188 TULLYLOST PRV.xlsx"
    )
    assert folder_path_from_web_url(url, is_folder=False) == (
        "Shared Documents / WATER CONTROL SHARED FOLDER / UE PCV SURVEY / KILDARE"
    )


def test_folder_path_for_folder_includes_its_own_name():
    url = "https://contoso.sharepoint.com/Shared Documents/WATER CONTROL SHARED FOLDER/KILDARE"
    assert folder_path_from_web_url(url, is_folder=True) == (
        "Shared Documents / WATER CONTROL SHARED FOLDER / KILDARE"
    )


def test_folder_path_decodes_url_encoded_segments():
    url = "https://contoso.sharepoint.com/Shared%20Documents/Health%20%26%20Safety/Policy.pdf"
    assert folder_path_from_web_url(url, is_folder=False) == "Shared Documents / Health & Safety"


def test_folder_path_empty_url():
    assert folder_path_from_web_url("", is_folder=False) == ""

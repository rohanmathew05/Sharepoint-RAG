"""Small helpers for shaping SharePoint/OneDrive URLs before they're
handed to the frontend as citation links."""
from urllib.parse import unquote, urlparse


def as_browser_viewable_url(url: str) -> str:
    """Appends the `web=1` query param SharePoint/OneDrive recognizes to
    force opening a file in the browser's Office Online viewer.

    Without it, a driveItem's raw `webUrl` often triggers a download (or
    hands off to the desktop Office app, if one's associated) instead of
    opening the file in SharePoint itself — not what a citation link
    should do.
    """
    if not url:
        return url
    separator = "&" if urlparse(url).query else "?"
    return f"{url}{separator}web=1"


def folder_path_from_web_url(url: str, is_folder: bool) -> str:
    """Derives a breadcrumb-style folder path from a driveItem's webUrl,
    e.g. "Shared Documents / WATER CONTROL SHARED FOLDER / UE PCV SURVEY / KILDARE"
    for a file at .../Shared Documents/WATER CONTROL SHARED FOLDER/UE PCV
    SURVEY/KILDARE/WFV0002188 TULLYLOST PRV.xlsx.

    Only uses the URL itself (always present on a search hit) rather than
    parentReference.path (which the Search API doesn't reliably return),
    so this works for every result without an extra Graph call.
    """
    if not url:
        return ""
    segments = [unquote(s) for s in urlparse(url).path.strip("/").split("/") if s]
    # A file's last segment is its own name, not part of the folder path;
    # a folder's last segment IS the folder itself, so keep it.
    if not is_folder and segments:
        segments = segments[:-1]
    return " / ".join(segments)

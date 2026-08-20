"""Small helpers for shaping SharePoint/OneDrive URLs before they're
handed to the frontend as citation links."""
from urllib.parse import urlparse


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

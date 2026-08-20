"""Unit tests for GraphService.search_sharepoint against a mocked
httpx.AsyncClient — no real Graph credentials or network access needed.
This is the only path now that DEMO_MODE has been removed, so it needs
real coverage of request construction and response parsing."""
import httpx
import pytest

from backend.services.graph import GraphAPIError, GraphService

SAMPLE_RESPONSE = {
    "value": [
        {
            "hitsContainers": [
                {
                    "total": 2,
                    "moreResultsAvailable": False,
                    "hits": [
                        {
                            "summary": "Survey Form <c0>Pressure Control Valve</c0>...",
                            "resource": {
                                "@odata.type": "#microsoft.graph.driveItem",
                                "id": "item-1",
                                "name": "WFV0002188 TULLYLOST PRV.xlsx",
                                "webUrl": (
                                    "https://contoso.sharepoint.com/Shared Documents/"
                                    "WATER CONTROL/KILDARE/WFV0002188 TULLYLOST PRV.xlsx"
                                ),
                                "lastModifiedDateTime": "2026-08-19T14:20:34Z",
                                "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                                "parentReference": {
                                    "siteId": "contoso.sharepoint.com,site-guid,web-guid",
                                    "driveId": "drive-guid",
                                },
                            },
                        },
                        {
                            "summary": "",
                            "resource": {
                                "@odata.type": "#microsoft.graph.driveItem",
                                "id": "folder-1",
                                "name": "KILDARE",
                                "webUrl": "https://contoso.sharepoint.com/Shared Documents/WATER CONTROL/KILDARE",
                                "folder": {"childCount": 12},
                                "parentReference": {
                                    "siteId": "contoso.sharepoint.com,site-guid,web-guid",
                                    "driveId": "drive-guid",
                                },
                            },
                        },
                    ],
                }
            ]
        }
    ]
}


class FakeResponse:
    def __init__(self, status_code, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}
        self.text = text

    @property
    def is_error(self):
        return self.status_code >= 400

    def json(self):
        return self._json_data


@pytest.mark.asyncio
async def test_search_sharepoint_parses_file_and_folder_hits(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResponse(200, json_data=SAMPLE_RESPONSE)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    service = GraphService("fake-delegated-token")
    results = await service.search_sharepoint("Tullylost", size=8)

    assert len(results) == 2

    file_doc = results[0]
    assert file_doc.document_name == "WFV0002188 TULLYLOST PRV.xlsx"
    assert file_doc.is_folder is False
    assert file_doc.folder_path == "Shared Documents / WATER CONTROL / KILDARE"
    assert file_doc.web_url.endswith("?web=1")

    folder_doc = results[1]
    assert folder_doc.document_name == "KILDARE"
    assert folder_doc.is_folder is True
    assert folder_doc.folder_path == "Shared Documents / WATER CONTROL / KILDARE"

    # The delegated token must be the one actually sent to Graph — this is
    # what makes retrieval permission-aware (Graph enforces access using
    # this exact token, not any app-level filtering).
    assert captured["headers"]["Authorization"] == "Bearer fake-delegated-token"
    assert captured["json"]["requests"][0]["query"]["queryString"] == "Tullylost"
    assert "fields" not in captured["json"]["requests"][0]
    assert "region" not in captured["json"]["requests"][0]


@pytest.mark.asyncio
async def test_rate_limit_raises_graph_api_error_with_retry_after(monkeypatch):
    async def fake_post(self, url, json=None, headers=None):
        return FakeResponse(429, headers={"Retry-After": "30"}, text="Too Many Requests")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    service = GraphService("fake-token")
    with pytest.raises(GraphAPIError) as exc_info:
        await service.search_sharepoint("test")

    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after == "30"


@pytest.mark.asyncio
async def test_other_error_status_raises_graph_api_error(monkeypatch):
    async def fake_post(self, url, json=None, headers=None):
        return FakeResponse(503, text="Service Unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    service = GraphService("fake-token")
    with pytest.raises(GraphAPIError) as exc_info:
        await service.search_sharepoint("test")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_empty_results_return_empty_list(monkeypatch):
    async def fake_post(self, url, json=None, headers=None):
        return FakeResponse(
            200,
            json_data={"value": [{"hitsContainers": [{"total": 0, "moreResultsAvailable": False, "hits": []}]}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    service = GraphService("fake-token")
    results = await service.search_sharepoint("nonexistent")
    assert results == []

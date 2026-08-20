"""Fixture SharePoint content used when DEMO_MODE=true.

This stands in for a real tenant so the permission-aware retrieval model
can be demonstrated end-to-end without live Entra ID / Graph credentials.
Each document is tagged with the SharePoint group that "owns" it; each
demo user is tagged with the groups they belong to. GraphService only
ever returns documents whose group the requesting user belongs to — the
same shape of enforcement Microsoft Graph performs for real, just backed
by this table instead of an actual SharePoint permission model.
"""
from backend.models.documents import DriveInfo, SiteInfo, SourceDocument

# group -> user oids that are members of it
GROUP_MEMBERSHIP: dict[str, set[str]] = {
    "General": {
        "00000000-0000-0000-0000-0000000000a1",  # User A
        "00000000-0000-0000-0000-0000000000b1",  # User B
    },
    "Health & Safety": {
        "00000000-0000-0000-0000-0000000000a1",
        "00000000-0000-0000-0000-0000000000b1",
    },
    "Engineering": {
        "00000000-0000-0000-0000-0000000000b1",  # only User B
    },
    "HR": set(),  # neither demo user belongs to HR
}

_SITE = SiteInfo(site_id="contoso.sharepoint.com,site1", site_name="Contoso Intranet", site_url="https://contoso.sharepoint.com/sites/intranet")
_DRIVE = DriveInfo(drive_id="drive1", drive_name="Documents")


def _doc(doc_id: str, name: str, group: str, content: str) -> dict:
    group_folder = group.replace(" & ", "").replace(" ", "")
    return {
        "group": group,
        "document": SourceDocument(
            document_id=doc_id,
            document_name=name,
            web_url=f"https://contoso.sharepoint.com/sites/intranet/{group_folder}/{name.replace(' ', '%20')}",
            site=_SITE,
            drive=_DRIVE,
            relevant_content=content,
            last_modified="2026-06-01T00:00:00Z",
            is_folder=False,
            folder_path=f"Shared Documents / {group}",
        ),
    }


DOCUMENT_LIBRARY: list[dict] = [
    _doc(
        "doc-hs-001",
        "Confined Space Policy.pdf",
        "Health & Safety",
        "Workers entering confined spaces must complete confined-space entry "
        "training and use a full-body harness, gas detector, and forced-air "
        "ventilation. Required PPE includes: full-body harness with rescue "
        "line, four-gas detector (O2, CO, H2S, LEL), hard hat, and "
        "chemical-resistant gloves. A trained attendant must remain outside "
        "the space at all times during entry.",
    ),
    _doc(
        "doc-hs-002",
        "PPE Requirements.docx",
        "Health & Safety",
        "General PPE requirements across all site work: hard hat, safety "
        "glasses, steel-toe boots, and hi-vis vest. For confined-space work, "
        "additional PPE is mandatory: full-body harness, four-gas detector, "
        "and a rescue retrieval line as described in the Confined Space "
        "Policy.",
    ),
    _doc(
        "doc-eng-001",
        "Pump Specifications.pdf",
        "Engineering",
        "Model P-450 centrifugal pump: max flow 450 L/min, max head 60m, "
        "operating temperature range -10C to 90C. Requires 3-phase 415V "
        "supply and quarterly seal inspection.",
    ),
    _doc(
        "doc-eng-002",
        "Installation Guide.pdf",
        "Engineering",
        "Installation steps for the P-450 pump skid: verify foundation "
        "level within 2mm, torque anchor bolts to 120Nm, align coupling "
        "within 0.05mm TIR before commissioning.",
    ),
    _doc(
        "doc-hr-001",
        "Salary Policy.pdf",
        "HR",
        "Salary bands are reviewed annually each April. Base pay adjustments "
        "are benchmarked against regional market data.",
    ),
    _doc(
        "doc-hr-002",
        "Holiday Policy.pdf",
        "HR",
        "Employees accrue 25 days annual leave, plus statutory public "
        "holidays. Unused leave may carry over up to 5 days into the next "
        "year.",
    ),
]


_STOPWORDS = {
    "the", "and", "for", "are", "what", "when", "where", "how", "does",
    "with", "that", "this", "have", "has", "can", "you", "your", "all",
    "any", "who", "why", "was", "were", "which", "our", "about",
}


def _user_groups(user_oid: str) -> set[str]:
    return {g for g, members in GROUP_MEMBERSHIP.items() if user_oid in members}


def search_demo_documents(user_oid: str, query: str, size: int = 8) -> list[SourceDocument]:
    """Keyword-match search over the fixture library, filtered to the
    groups the requesting user belongs to. This mirrors what Microsoft
    Graph's Search API does for a real tenant: only documents within the
    caller's own permissions are ever candidates for retrieval.
    """
    allowed_groups = _user_groups(user_oid)
    query_terms = [
        t.lower().strip("?.,!")
        for t in query.split()
        if len(t) > 2 and t.lower().strip("?.,!") not in _STOPWORDS
    ]

    matches: list[tuple[int, SourceDocument]] = []
    for entry in DOCUMENT_LIBRARY:
        if entry["group"] not in allowed_groups:
            continue  # permission boundary: never surfaced to this user
        doc: SourceDocument = entry["document"]
        haystack = f"{doc.document_name} {doc.relevant_content}".lower()
        score = sum(1 for term in query_terms if term in haystack)
        if score > 0 or not query_terms:
            matches.append((score, doc))

    matches.sort(key=lambda pair: pair[0], reverse=True)
    return [doc for _, doc in matches[:size]]

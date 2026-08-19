import type { Citation } from "../types";

export function SourceCard({ citation }: { citation: Citation }) {
  return (
    <a
      className="source-card"
      href={citation.web_url}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className="source-icon">📄</span>
      <span className="source-name">{citation.document_name}</span>
      <span className="source-link-icon">↗</span>
    </a>
  );
}

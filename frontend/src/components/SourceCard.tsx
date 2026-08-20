import type { Citation } from "../types";
import { getSourceIcon } from "../utils/fileIcons";

export function SourceCard({ citation }: { citation: Citation }) {
  return (
    <a
      className="source-card"
      href={citation.web_url}
      target="_blank"
      rel="noopener noreferrer"
    >
      <span className="source-icon">{getSourceIcon(citation.document_name, citation.is_folder)}</span>
      <span className="source-text">
        <span className="source-name">{citation.document_name}</span>
        {citation.folder_path && (
          <span className="source-path">{citation.folder_path}</span>
        )}
      </span>
      <span className="source-link-icon">↗</span>
    </a>
  );
}

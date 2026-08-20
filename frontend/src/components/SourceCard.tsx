import type { Citation } from "../types";
import { FileTypeIcon } from "./FileTypeIcon";

export function SourceCard({ citation }: { citation: Citation }) {
  return (
    <a
      className="source-card"
      href={citation.web_url}
      target="_blank"
      rel="noopener noreferrer"
    >
      <FileTypeIcon documentName={citation.document_name} isFolder={citation.is_folder} />
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

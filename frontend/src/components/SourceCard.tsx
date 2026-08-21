import type { Citation } from "../types";
import { FileTypeIcon } from "./FileTypeIcon";

export function SourceCard({ citation }: { citation: Citation }) {
  return (
    <a
      className="flex items-start gap-2.5 rounded-md border border-border bg-surface px-3 py-2.5 text-sm text-foreground no-underline transition-colors hover:bg-surface-alt"
      href={citation.web_url}
      target="_blank"
      rel="noopener noreferrer"
    >
      <FileTypeIcon documentName={citation.document_name} isFolder={citation.is_folder} />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate">{citation.document_name}</span>
        {citation.folder_path && (
          <span className="truncate text-xs text-muted-foreground">{citation.folder_path}</span>
        )}
      </span>
      <span className="pt-0.5 text-muted-foreground">↗</span>
    </a>
  );
}

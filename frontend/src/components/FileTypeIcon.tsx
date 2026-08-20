// Small colored badge icons matching Office's brand colors, so a source
// card reads at a glance as "Excel" / "Word" / "PDF" / "PowerPoint"
// rather than a generic document glyph. Inline SVG (no external image
// requests) so this never depends on network access or a CDN.
const OFFICE_ICONS: Record<string, { color: string; label: string }> = {
  xlsx: { color: "#217346", label: "X" },
  xls: { color: "#217346", label: "X" },
  csv: { color: "#217346", label: "X" },
  docx: { color: "#2B579A", label: "W" },
  doc: { color: "#2B579A", label: "W" },
  pdf: { color: "#E03E2D", label: "PDF" },
  pptx: { color: "#D24726", label: "P" },
  ppt: { color: "#D24726", label: "P" },
};

function getExtension(documentName: string): string {
  return documentName.split(".").pop()?.toLowerCase() ?? "";
}

export function FileTypeIcon({
  documentName,
  isFolder,
}: {
  documentName: string;
  isFolder: boolean;
}) {
  if (isFolder) {
    return (
      <span className="source-icon-emoji" role="img" aria-label="Folder">
        📁
      </span>
    );
  }

  const icon = OFFICE_ICONS[getExtension(documentName)];
  if (!icon) {
    return (
      <span className="source-icon-emoji" role="img" aria-label="Document">
        📄
      </span>
    );
  }

  return (
    <svg
      className="source-icon-badge"
      width="20"
      height="20"
      viewBox="0 0 20 20"
      role="img"
      aria-label={icon.label === "PDF" ? "PDF document" : icon.label === "X" ? "Excel spreadsheet" : icon.label === "W" ? "Word document" : "PowerPoint presentation"}
    >
      <rect x="1" y="1" width="18" height="18" rx="3" fill={icon.color} />
      <text
        x="10"
        y={icon.label.length > 1 ? "13" : "14"}
        textAnchor="middle"
        fontSize={icon.label.length > 1 ? "6.5" : "10"}
        fontWeight="700"
        fill="white"
        fontFamily="Segoe UI, Arial, sans-serif"
      >
        {icon.label}
      </text>
    </svg>
  );
}

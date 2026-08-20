const ICONS_BY_EXTENSION: Record<string, string> = {
  xlsx: "📊",
  xls: "📊",
  csv: "📊",
  docx: "📝",
  doc: "📝",
  txt: "📝",
  pdf: "📕",
  pptx: "📽️",
  ppt: "📽️",
};

const FOLDER_ICON = "📁";
const DEFAULT_FILE_ICON = "📄";

export function getSourceIcon(documentName: string, isFolder: boolean): string {
  if (isFolder) return FOLDER_ICON;
  const extension = documentName.split(".").pop()?.toLowerCase();
  if (!extension) return DEFAULT_FILE_ICON;
  return ICONS_BY_EXTENSION[extension] ?? DEFAULT_FILE_ICON;
}

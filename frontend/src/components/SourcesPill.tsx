import { FileText } from "lucide-react";
import type { Citation } from "../types";
import { Badge } from "./ui/badge";

export function SourcesPill({
  citations,
  onOpen,
}: {
  citations: Citation[];
  onOpen: (citations: Citation[]) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onOpen(citations)}
      className="mt-3 inline-flex focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-full"
    >
      <Badge className="cursor-pointer hover:bg-primary hover:text-primary-foreground">
        <FileText className="h-3.5 w-3.5" />
        {citations.length} {citations.length === 1 ? "Source" : "Sources"}
      </Badge>
    </button>
  );
}

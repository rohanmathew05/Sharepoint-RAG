export interface Citation {
  document_id: string;
  document_name: string;
  web_url: string;
  is_folder: boolean;
  folder_path: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isError?: boolean;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  retrieval_attempts: number;
}

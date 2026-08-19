export interface Citation {
  document_id: string;
  document_name: string;
  web_url: string;
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

export interface DemoUser {
  id: string;
  label: string;
  groups: string[];
}

export const DEMO_USERS: DemoUser[] = [
  { id: "user-a", label: "User A — General only", groups: ["General", "Health & Safety"] },
  {
    id: "user-b",
    label: "User B — General + Engineering",
    groups: ["General", "Health & Safety", "Engineering"],
  },
];

// Mirrors backend/app/modules/chat/schemas.py (snake_case on purpose)
export const CHAT_MAX_CHARS = 4000;
export const CHAT_HOURLY_LIMIT = 20;

export type ChatRole = 'user' | 'assistant';

export type ChatSource = {
  id: string; // "S1" … as cited in the answer
  title: string;
  section: string;
  version: string; // the NEI page's "Last updated" date
  url: string;
  review_status: string;
};

export type ChatMessage = {
  id: number;
  role: ChatRole;
  content: string;
  in_scope?: boolean | null; // assistant only: false for an off-topic redirect
  sources: ChatSource[];
  created_at: string;
};

export type ChatExchange = { user_message: ChatMessage; assistant_message: ChatMessage };

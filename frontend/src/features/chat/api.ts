import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../lib/api/client';
import type { Envelope } from '../../lib/api/types';
import type { ChatExchange, ChatMessage } from './types';

const chatKey = (screeningId: number) => ['chat', screeningId] as const;

/** The screening's chat thread, oldest first. */
export function useChat(screeningId: number, enabled = true) {
  return useQuery({
    queryKey: chatKey(screeningId),
    queryFn: () => client.get<Envelope<ChatMessage[]>>(`/screenings/${screeningId}/chat`).then((r) => r.data.data),
    enabled: enabled && Number.isInteger(screeningId) && screeningId > 0,
    retry: (count, err) => (err as { response?: { status?: number } })?.response?.status !== 404 && count < 1,
  });
}

/** Ask a question. On success both new messages are appended to the cached thread (no refetch needed). */
export function useSendChat(screeningId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (message: string) =>
      client.post<Envelope<ChatExchange>>(`/screenings/${screeningId}/chat`, { message }).then((r) => r.data.data),
    onSuccess: ({ user_message, assistant_message }) => {
      qc.setQueryData<ChatMessage[]>(chatKey(screeningId), (old) => [...(old ?? []), user_message, assistant_message]);
    },
  });
}

import { useQuery } from '@tanstack/react-query';
import { client } from '../../lib/api/client';
import type { Envelope, ModelCard } from '../../lib/api/types';

export function useModelCard() {
  return useQuery({
    queryKey: ['model'],
    queryFn: () => client.get<Envelope<ModelCard>>('/model').then((r) => r.data.data),
    staleTime: Infinity,
  });
}

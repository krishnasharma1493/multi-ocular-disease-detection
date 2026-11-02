import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../lib/api/client';
import type { Envelope, Review, ReviewInput } from '../../lib/api/types';

export function useReviews(screeningId: number, enabled = true) {
  return useQuery({
    queryKey: ['screenings', 'reviews', screeningId],
    queryFn: () => client.get<Envelope<Review[]>>(`/screenings/${screeningId}/reviews`).then((r) => r.data.data),
    enabled,
  });
}

export function useCreateReview(screeningId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ReviewInput) =>
      client.post<Envelope<Review>>(`/screenings/${screeningId}/reviews`, body).then((r) => r.data.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['screenings'] }),
  });
}

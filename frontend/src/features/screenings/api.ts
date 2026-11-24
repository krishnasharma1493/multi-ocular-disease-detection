import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { client } from '../../lib/api/client';
import type {
  Envelope, Page, Screening, ScreeningInput, ScreeningResult, ScreeningStats, ScreeningStatus, ScreeningUpdate,
} from '../../lib/api/types';

export type ListParams = { page?: number; limit?: number; q?: string; status?: ScreeningStatus };

export function useScreenings(params: ListParams) {
  return useQuery({
    queryKey: ['screenings', 'list', params],
    queryFn: () => client.get<Page<Screening>>('/screenings', { params }).then((r) => r.data),
    placeholderData: keepPreviousData,
  });
}

/**
 * Every screening matching a status, across all pages (the API caps `limit` at 100). The list page searches by
 * date and eye, which the API cannot filter on, so the search runs over the full set instead of the first page.
 */
export function useAllScreenings(status: ScreeningStatus | undefined, enabled: boolean) {
  return useQuery({
    queryKey: ['screenings', 'all', status ?? ''],
    queryFn: async () => {
      const get = (page: number) =>
        client.get<Page<Screening>>('/screenings', { params: { page, limit: 100, status } }).then((r) => r.data);
      const first = await get(1);
      const rest = await Promise.all(
        Array.from({ length: Math.max(0, first.pagination.total_pages - 1) }, (_, i) => get(i + 2)),
      );
      return [first, ...rest].flatMap((p) => p.data);
    },
    enabled,
    placeholderData: keepPreviousData,
  });
}

export function useScreeningStats() {
  return useQuery({
    queryKey: ['screenings', 'stats'],
    queryFn: () => client.get<Envelope<ScreeningStats>>('/screenings/stats').then((r) => r.data.data),
  });
}

export function useScreening(id: number) {
  return useQuery({
    queryKey: ['screenings', 'one', id],
    queryFn: () => client.get<Envelope<Screening>>(`/screenings/${id}`).then((r) => r.data.data),
    enabled: Number.isInteger(id) && id > 0,
    retry: (count, err) => (err as { response?: { status?: number } })?.response?.status !== 404 && count < 1,
  });
}

/** Changes only when the photo itself changes (not on reviews or edits), so the cached blob stays valid. */
export const photoVersion = (s?: Screening) => (s?.image ? `${s.image.name}:${s.image.bytes}:${s.image.width}x${s.image.height}` : s?.updated_at);

/** <img src> cannot send the Authorization header, so the photo is fetched as a blob. */
export function useScreeningImage(id: number, version: string | undefined, enabled: boolean) {
  const query = useQuery({
    queryKey: ['screening-image', id, version],
    queryFn: () => client.get<Blob>(`/screenings/${id}/image`, { responseType: 'blob' }).then((r) => r.data),
    enabled,
    staleTime: Infinity,
  });
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!query.data) return;
    const objectUrl = URL.createObjectURL(query.data);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [query.data]);
  return { ...query, url };
}

export function useCreateScreening() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ScreeningInput) => client.post<Envelope<Screening>>('/screenings', body).then((r) => r.data.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['screenings'] }),
  });
}

export function useUploadImage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, file, onProgress }: { id: number; file: File; onProgress?: (loaded: number, total: number) => void }) => {
      const form = new FormData();
      form.append('file', file);
      return client
        .put<Envelope<Screening>>(`/screenings/${id}/image`, form, {
          onUploadProgress: (e) => onProgress?.(e.loaded, e.total ?? file.size),
        })
        .then((r) => r.data.data);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['screenings'] }),
  });
}

export function useUpdateScreening() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: ScreeningUpdate & { id: number }) =>
      client.patch<Envelope<Screening>>(`/screenings/${id}`, body).then((r) => r.data.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['screenings'] }),
  });
}

export function useDeleteScreening() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => client.delete(`/screenings/${id}`),
    onSuccess: (_d, id) => {
      qc.removeQueries({ queryKey: ['screenings', 'one', id] });
      return qc.invalidateQueries({ queryKey: ['screenings'] });
    },
  });
}

export function useAnalyzeScreening() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => client.post<Envelope<ScreeningResult>>(`/screenings/${id}/analyze`).then((r) => r.data.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['screenings'] }),
  });
}

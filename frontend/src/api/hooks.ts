import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, qs } from '@/api/client';
import { hotelKey } from '@/api/realtime';
import { useHotel } from '@/auth/AuthProvider';

type Params = Record<string, string | number | boolean | null | undefined>;

/** GET a hotel-scoped resource, cached under ['h', hotelId, entity, ...]. */
export function useHotelQuery<T>(entity: string, path: string, params?: Params, enabled = true) {
  const hotel = useHotel();
  return useQuery({
    queryKey: hotelKey(hotel.id, entity, path, params ?? {}),
    queryFn: ({ signal }) => api.get<T>(`/hotels/${hotel.id}${path}${qs(params ?? {})}`, signal),
    enabled,
  });
}

/**
 * A mutation on hotel-scoped resources. On success the listed entity caches
 * are invalidated locally right away (other devices are updated by the
 * WebSocket event the server emits on commit).
 */
export function useHotelMutation<TInput, TOutput = unknown>(
  fn: (hotelPath: (p: string) => string, input: TInput) => Promise<TOutput>,
  invalidates: string[],
) {
  const hotel = useHotel();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: TInput) => fn((p) => `/hotels/${hotel.id}${p}`, input),
    onSuccess: () => {
      for (const entity of invalidates) void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, entity) });
    },
  });
}

/** CRUD helpers for the common create / update / delete shape. */
export function useCrud<T extends { id: string }, TCreate = Partial<T>>(entity: string, path: string, invalidates?: string[]) {
  const targets = invalidates ?? [entity];
  const create = useHotelMutation<TCreate, T>((h, body) => api.post<T>(h(path), body), targets);
  const update = useHotelMutation<{ id: string; body: Record<string, unknown> }, T>(
    (h, { id, body }) => api.patch<T>(h(`${path}/${id}`), body),
    targets,
  );
  const remove = useHotelMutation<string, void>((h, id) => api.delete(h(`${path}/${id}`)), targets);
  return { create, update, remove };
}

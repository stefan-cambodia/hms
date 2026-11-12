import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { api, ApiError, setCsrfToken, setUnauthorizedHandler } from '@/api/client';
import type { HotelAccess, Me } from '@/api/types';
import { applyLanguage, isLanguage, type LanguageCode } from '@/i18n';

const HOTEL_KEY = 'hms.hotel';

type Status = 'loading' | 'anonymous' | 'authenticated';

interface LoginInput {
  email: string;
  password: string;
  totp_code?: string;
}

interface AuthContextValue {
  status: Status;
  me: Me | null;
  hotel: HotelAccess | null;
  selectHotel: (id: string) => void;
  can: (permission: string) => boolean;
  login: (input: LoginInput) => Promise<Me>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setLanguage: (lang: LanguageCode) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function deviceLabel(): string {
  const ua = navigator.userAgent;
  if (/iPad|Macintosh.*Mobile/.test(ua)) return 'iPad';
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? 'Android phone' : 'Android tablet';
  if (/Windows/.test(ua)) return 'Windows';
  if (/Linux/.test(ua)) return 'Linux';
  if (/Mac/.test(ua)) return 'macOS';
  return 'Browser';
}

function readStoredHotel(): string | null {
  try {
    return localStorage.getItem(HOTEL_KEY);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>('loading');
  const [me, setMe] = useState<Me | null>(null);
  const [hotelId, setHotelId] = useState<string | null>(readStoredHotel);

  const accept = useCallback(async (data: Me) => {
    setCsrfToken(data.csrf_token);
    setMe(data);
    setStatus('authenticated');
    if (isLanguage(data.user.preferred_language)) await applyLanguage(data.user.preferred_language);
  }, []);

  const reset = useCallback(() => {
    setCsrfToken(null);
    setMe(null);
    setStatus('anonymous');
    queryClient.clear();
  }, [queryClient]);

  const refresh = useCallback(async () => {
    try {
      await accept(await api.get<Me>('/auth/me'));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) reset();
      else throw err;
    }
  }, [accept, reset]);

  useEffect(() => {
    setUnauthorizedHandler(reset);
    refresh().catch(() => setStatus('anonymous'));
    return () => setUnauthorizedHandler(null);
  }, [refresh, reset]);

  const login = useCallback(
    async (input: LoginInput) => {
      const data = await api.post<Me>('/auth/login', { ...input, device_label: deviceLabel() });
      queryClient.clear();
      await accept(data);
      return data;
    },
    [accept, queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await api.post('/auth/logout');
    } finally {
      reset();
    }
  }, [reset]);

  const setLanguage = useCallback(
    async (lang: LanguageCode) => {
      await applyLanguage(lang);
      if (status === 'authenticated') {
        const data = await api.patch<Me>('/auth/me', { preferred_language: lang });
        setMe(data);
      }
    },
    [status],
  );

  const hotel = useMemo(() => {
    if (!me || me.hotels.length === 0) return null;
    return me.hotels.find((h) => h.id === hotelId) ?? me.hotels[0];
  }, [me, hotelId]);

  const selectHotel = useCallback(
    (id: string) => {
      setHotelId(id);
      try {
        localStorage.setItem(HOTEL_KEY, id);
      } catch {
        /* ignore */
      }
      queryClient.clear();
    },
    [queryClient],
  );

  const can = useCallback((permission: string) => !!hotel?.permissions.includes(permission), [hotel]);

  const value = useMemo(
    () => ({ status, me, hotel, selectHotel, can, login, logout, refresh, setLanguage }),
    [status, me, hotel, selectHotel, can, login, logout, refresh, setLanguage],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth outside AuthProvider');
  return ctx;
}

/** Current hotel (only valid inside authenticated routes). */
export function useHotel(): HotelAccess {
  const { hotel } = useAuth();
  if (!hotel) throw new Error('No hotel selected');
  return hotel;
}

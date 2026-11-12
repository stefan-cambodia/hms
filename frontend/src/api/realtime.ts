/**
 * Real-time synchronisation client.
 *
 * The server pushes small change events; we never trust pushed data, we only
 * invalidate the affected queries so they refetch through the REST API with
 * normal permission checks. After any reconnect (or a server "resync") every
 * query is invalidated because events may have been missed meanwhile.
 */
import { useEffect, useSyncExternalStore } from 'react';
import { type QueryClient, useQueryClient } from '@tanstack/react-query';

export type ConnectionStatus = 'connecting' | 'online' | 'offline';

export interface ChangeEvent {
  type: 'event';
  hotel_id: string | null;
  entity: string;
  action: string;
  id: string | null;
  version: number | null;
  actor: string | null;
}

// Which cached entity lists an event about `entity` can affect.
const DEPENDENTS: Record<string, string[]> = {
  hotel: ['hotel'],
  building: ['building', 'floor', 'room'],
  floor: ['floor', 'room'],
  room_type: ['room_type', 'room'],
  room: ['room', 'room_type'],
  amenity: ['amenity', 'room_type', 'room'],
  facility: ['facility', 'service'],
  service: ['service'],
  tax_rate: ['tax_rate'],
  user: ['user', 'session'],
  role: ['role', 'user'],
  session: ['session', 'user'],
};
// Events that may change the current user's own profile or permissions.
const AFFECTS_ME = new Set(['hotel', 'role', 'user']);

const HEARTBEAT_TIMEOUT = 40_000;
const CONNECT_TIMEOUT = 15_000;

let status: ConnectionStatus = 'connecting';
const listeners = new Set<() => void>();

function setStatus(next: ConnectionStatus): void {
  if (status !== next) {
    status = next;
    listeners.forEach((l) => l());
  }
}

export function useConnectionStatus(): ConnectionStatus {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => status,
  );
}

export function hotelKey(hotelId: string, entity: string, ...rest: unknown[]): unknown[] {
  return ['h', hotelId, entity, ...rest];
}

export function invalidateForEvent(qc: QueryClient, hotelId: string, entity: string): void {
  const targets = DEPENDENTS[entity];
  if (!targets) {
    void qc.invalidateQueries({ queryKey: ['h', hotelId] });
    return;
  }
  for (const target of targets) void qc.invalidateQueries({ queryKey: hotelKey(hotelId, target) });
  // Every change writes an audit record.
  void qc.invalidateQueries({ queryKey: hotelKey(hotelId, 'audit') });
}

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/api/v1/ws`;
}

interface Options {
  hotelId: string;
  queryClient: QueryClient;
  onMeChanged: () => void;
  onSessionEnded: () => void;
}

/** Opens and maintains the socket; returns a disposer. */
export function connectRealtime({ hotelId, queryClient, onMeChanged, onSessionEnded }: Options): () => void {
  let ws: WebSocket | null = null;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  let everConnected = false;
  let lastActivity = Date.now();

  const resyncAll = () => {
    void queryClient.invalidateQueries({ queryKey: ['h', hotelId] });
    onMeChanged();
  };

  const scheduleReconnect = () => {
    if (disposed) return;
    setStatus('offline');
    // Exponential backoff with jitter, capped at 30 s.
    const delay = Math.min(30_000, 1000 * 2 ** Math.min(attempt, 5)) * (0.7 + Math.random() * 0.6);
    attempt += 1;
    timer = setTimeout(open, delay);
  };

  /**
   * Drop a socket we no longer trust without waiting for its close handshake
   * (on a dead network the browser may not fire `onclose` for minutes).
   */
  const abandon = () => {
    const dead = ws;
    ws = null;
    if (dead) {
      dead.onopen = dead.onmessage = dead.onclose = dead.onerror = null;
      try {
        dead.close();
      } catch {
        /* already closed */
      }
    }
    clearTimeout(timer);
    scheduleReconnect();
  };

  function open(): void {
    if (disposed) return;
    setStatus('connecting');
    lastActivity = Date.now();
    ws = new WebSocket(wsUrl());
    ws.onopen = () => {
      lastActivity = Date.now();
      ws?.send(JSON.stringify({ type: 'subscribe', hotel_id: hotelId }));
    };
    ws.onmessage = (msg) => {
      lastActivity = Date.now();
      let data: { type: string; entity?: string };
      try {
        data = JSON.parse(msg.data as string);
      } catch {
        return;
      }
      switch (data.type) {
        case 'ready':
          attempt = 0;
          setStatus('online');
          if (everConnected) resyncAll(); // events may have been missed while away
          everConnected = true;
          break;
        case 'event':
          if (data.entity) {
            invalidateForEvent(queryClient, hotelId, data.entity);
            if (AFFECTS_ME.has(data.entity)) onMeChanged();
          }
          break;
        case 'resync':
          resyncAll();
          break;
        case 'ping':
          ws?.send(JSON.stringify({ type: 'pong' }));
          break;
      }
    };
    ws.onclose = (event) => {
      ws = null;
      if (disposed) return;
      if (event.code === 4401) {
        setStatus('offline');
        onSessionEnded();
        return;
      }
      scheduleReconnect();
    };
  }

  const onOnline = () => {
    if (!ws && !disposed) {
      clearTimeout(timer);
      attempt = 0;
      open();
    }
  };
  const onOffline = () => {
    if (!disposed) abandon();
  };
  // Watchdog: the server pings every 25 s. Silence for longer means the link
  // is dead even if the browser still reports the socket as open.
  const watchdog = setInterval(() => {
    if (!ws || disposed) return;
    const silent = Date.now() - lastActivity;
    if ((ws.readyState === WebSocket.OPEN && silent > HEARTBEAT_TIMEOUT) || (ws.readyState === WebSocket.CONNECTING && silent > CONNECT_TIMEOUT)) {
      abandon();
    }
  }, 5_000);
  window.addEventListener('online', onOnline);
  window.addEventListener('offline', onOffline);
  open();

  return () => {
    disposed = true;
    clearTimeout(timer);
    clearInterval(watchdog);
    window.removeEventListener('online', onOnline);
    window.removeEventListener('offline', onOffline);
    if (ws) {
      ws.onclose = null;
      ws.close();
    }
    setStatus('connecting');
  };
}

export function useRealtime(hotelId: string | undefined, onMeChanged: () => void, onSessionEnded: () => void): void {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!hotelId) return;
    return connectRealtime({ hotelId, queryClient, onMeChanged, onSessionEnded });
  }, [hotelId, queryClient, onMeChanged, onSessionEnded]);
}

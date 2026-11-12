import { type CSSProperties, type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from 'react';
import { Box, Group, Text, Tooltip } from '@mantine/core';
import { IconArrowBarRight, IconArrowBarToRight, IconTool } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import type { Availability, CalendarItem, Room, RoomType } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { addDays, dayLabel, eachDay, weekday } from '@/lib/dates';
import { pickLocalized } from '@/lib/localized';
import { barGeometry, dayShift, isMovable, STATUS_COLORS, stackLanes } from './layout';

export const LABEL_W = 136;
const ROW_H = 40;
const HEADER_H = 54;

type Row =
  | { kind: 'group'; key: string; type: RoomType; nights: Map<string, { available: number; total: number }> }
  | { kind: 'unassigned'; key: string; type: RoomType; items: CalendarItem[] }
  | { kind: 'room'; key: string; room: Room; items: CalendarItem[] };

export interface MoveRequest {
  item: CalendarItem;
  roomId: string | null;
  start: string;
  end: string;
}

interface DragState {
  item: CalendarItem;
  originRoom: string | null;
  originTop: number;
  x0: number;
  y0: number;
  active: boolean;
  shift: number;
  dy: number;
  targetRoom: string | null | undefined; // undefined = not over a valid row
}

export interface TimelineProps {
  start: string;
  days: number;
  colWidth: number;
  rooms: Room[];
  types: RoomType[];
  items: CalendarItem[];
  unassigned: CalendarItem[];
  availability: Availability[];
  today: string;
  highlight: string;
  canCreate: boolean;
  canMove: boolean;
  onCreate: (room: Room, date: string) => void;
  onOpen: (item: CalendarItem) => void;
  onMove: (move: MoveRequest) => void;
}

export function Timeline(props: TimelineProps) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { start, days, colWidth: W, today } = props;
  const dates = useMemo(() => eachDay(start, addDays(start, days)), [start, days]);
  const trackW = days * W;

  const rows = useMemo<Row[]>(() => {
    const byRoom = new Map<string, CalendarItem[]>();
    for (const it of props.items) if (it.room_id) byRoom.set(it.room_id, [...(byRoom.get(it.room_id) ?? []), it]);
    const out: Row[] = [];
    for (const type of props.types) {
      const typeRooms = props.rooms.filter((r) => r.room_type_id === type.id && r.is_active);
      const lanes = stackLanes(props.unassigned.filter((u) => u.room_type_id === type.id));
      if (!typeRooms.length && !lanes.length) continue;
      const av = props.availability.find((a) => a.room_type_id === type.id);
      out.push({ kind: 'group', key: `g-${type.id}`, type, nights: new Map((av?.nights ?? []).map((n) => [n.night, n])) });
      const laneCount = lanes.reduce((m, l) => Math.max(m, l.lane + 1), 0);
      for (let lane = 0; lane < laneCount; lane++) {
        out.push({ kind: 'unassigned', key: `u-${type.id}-${lane}`, type, items: lanes.filter((l) => l.lane === lane).map((l) => l.item) });
      }
      for (const room of typeRooms) out.push({ kind: 'room', key: `r-${room.id}`, room, items: byRoom.get(room.id) ?? [] });
    }
    return out;
  }, [props.items, props.unassigned, props.rooms, props.types, props.availability]);

  // --- drag & drop (mouse drag, or long-press on touch screens) --------------
  const [drag, setDrag] = useState<DragState | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const suppressClick = useRef(false);
  const update = (d: DragState | null) => {
    dragRef.current = d;
    setDrag(d);
  };

  useEffect(() => {
    // While dragging on a touch screen, stop the page from scrolling.
    const block = (e: TouchEvent) => {
      if (dragRef.current?.active) e.preventDefault();
    };
    document.addEventListener('touchmove', block, { passive: false });
    return () => document.removeEventListener('touchmove', block);
  }, []);

  const beginDrag = (e: ReactPointerEvent<HTMLDivElement>, item: CalendarItem, originRoom: string | null) => {
    if (!props.canMove || item.kind !== 'stay' || !isMovable(item.status) || e.button > 0) return;
    const rowEl = (e.currentTarget.closest('[data-drop-row]') as HTMLElement | null)?.getBoundingClientRect();
    const state: DragState = { item, originRoom, originTop: rowEl?.top ?? 0, x0: e.clientX, y0: e.clientY, active: false, shift: 0, dy: 0, targetRoom: originRoom };
    update(state);
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (e.pointerType === 'touch') timer = setTimeout(() => dragRef.current && update({ ...dragRef.current, active: true }), 350);

    const move = (ev: PointerEvent) => {
      const d = dragRef.current;
      if (!d) return;
      const dist = Math.hypot(ev.clientX - d.x0, ev.clientY - d.y0);
      if (!d.active) {
        if (ev.pointerType === 'touch') {
          if (dist > 8) cleanup(); // the user is scrolling, not dragging
          return;
        }
        if (dist < 5) return;
      }
      // Auto-scroll when dragging near the edges of the scrolling calendar.
      const scroller = rootRef.current?.parentElement;
      if (scroller) {
        const box = scroller.getBoundingClientRect();
        const edge = 48;
        if (ev.clientY > box.bottom - edge) scroller.scrollTop += 16;
        else if (ev.clientY < box.top + edge + HEADER_H) scroller.scrollTop -= 16;
        if (ev.clientX > box.right - edge) scroller.scrollLeft += 16;
        else if (ev.clientX < box.left + LABEL_W + edge) scroller.scrollLeft -= 16;
      }
      const target = document.elementsFromPoint(ev.clientX, ev.clientY).find((el) => (el as HTMLElement).dataset?.dropRow !== undefined) as HTMLElement | undefined;
      const rect = target?.getBoundingClientRect();
      update({
        ...d,
        active: true,
        shift: dayShift(ev.clientX - d.x0, W),
        dy: rect ? rect.top - d.originTop : ev.clientY - d.y0,
        targetRoom: target ? (target.dataset.dropRow || null) : undefined,
      });
    };
    const up = () => {
      const d = dragRef.current;
      cleanup();
      if (!d?.active) return;
      suppressClick.current = true;
      setTimeout(() => (suppressClick.current = false), 50);
      if (d.targetRoom === undefined) return;
      if (d.shift === 0 && d.targetRoom === d.originRoom) return;
      props.onMove({ item: d.item, roomId: d.targetRoom, start: addDays(d.item.start, d.shift), end: addDays(d.item.end, d.shift) });
    };
    const cleanup = () => {
      clearTimeout(timer);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', cleanup);
      update(null);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', cleanup);
  };

  // --- rendering -------------------------------------------------------------
  const term = props.highlight.trim().toLowerCase();
  const matches = (it: CalendarItem) => !term || `${it.guest_name ?? ''} ${it.code ?? ''}`.toLowerCase().includes(term);

  const renderBar = (it: CalendarItem, originRoom: string | null) => {
    const geo = barGeometry(it.start, it.end, start, days, W, 3);
    if (!geo) return null;
    const dragging = drag?.active && drag.item.id === it.id;
    const block = it.kind === 'block';
    const color = block ? 'gray' : STATUS_COLORS[it.status ?? 'confirmed'];
    const style: CSSProperties = {
      position: 'absolute',
      top: 5,
      height: ROW_H - 10,
      left: geo.left,
      width: geo.width,
      borderRadius: 6,
      background: block
        ? 'repeating-linear-gradient(135deg, var(--mantine-color-gray-2) 0 6px, var(--mantine-color-gray-3) 6px 12px)'
        : `color-mix(in srgb, var(--mantine-color-${color}-filled) 20%, var(--mantine-color-body))`,
      borderLeft: geo.clippedStart ? 'none' : `4px solid var(--mantine-color-${color}-filled)`,
      color: 'var(--mantine-color-text)',
      padding: '0 6px',
      display: 'flex',
      alignItems: 'center',
      gap: 4,
      overflow: 'hidden',
      cursor: block ? 'pointer' : props.canMove && isMovable(it.status) ? 'grab' : 'pointer',
      opacity: matches(it) ? 1 : 0.25,
      transform: dragging ? `translate(${drag!.shift * W}px, ${drag!.dy}px)` : undefined,
      zIndex: dragging ? 30 : 2,
      boxShadow: dragging ? 'var(--mantine-shadow-lg)' : undefined,
      outline: dragging && drag!.targetRoom === undefined ? '2px dashed var(--mantine-color-red-6)' : undefined,
      userSelect: 'none',
      WebkitUserSelect: 'none',
      touchAction: 'pan-x pan-y',
    };
    const label = block ? t(`calendar.block_reasons.${it.block_reason}`) : it.guest_name;
    return (
      <Tooltip
        key={it.id}
        disabled={!!drag}
        label={block ? label : `${it.code} · ${it.guest_name} · ${t(`reservations.status.${it.status}`)} · ${t('reservations.guests_count', { adults: it.adults ?? 0, children: it.children ?? 0 })}`}
        openDelay={400}
      >
        <div
          role="button"
          tabIndex={0}
          aria-label={block ? label ?? '' : `${it.code} ${it.guest_name}`}
          data-calendar-item={it.kind}
          style={style}
          onPointerDown={(e) => beginDrag(e, it, originRoom)}
          onClick={(e) => {
            e.stopPropagation();
            if (!suppressClick.current) props.onOpen(it);
          }}
          onKeyDown={(e) => e.key === 'Enter' && props.onOpen(it)}
        >
          {block && <IconTool size={14} style={{ flex: 'none' }} />}
          {!block && geo.width > 90 && !geo.clippedStart && it.start >= start && <IconArrowBarRight size={13} style={{ flex: 'none', opacity: 0.7 }} aria-hidden />}
          <Text size="xs" fw={600} truncate style={{ flex: 1 }}>
            {label}
          </Text>
          {!block && geo.width > 180 && (
            <Text size="xs" c="dimmed" className="hms-num" style={{ flex: 'none' }}>
              {it.code}
            </Text>
          )}
          {!block && geo.width > 90 && !geo.clippedEnd && <IconArrowBarToRight size={13} style={{ flex: 'none', opacity: 0.5 }} aria-hidden />}
        </div>
      </Tooltip>
    );
  };

  const trackBackground = `repeating-linear-gradient(to right, transparent 0 ${W - 1}px, var(--mantine-color-default-border) ${W - 1}px ${W}px)`;

  return (
    <Box ref={rootRef} style={{ position: 'relative', width: LABEL_W + trackW, minWidth: '100%', userSelect: 'none', WebkitUserSelect: 'none' }}>
      {/* Weekend and today shading behind all rows */}
      <div aria-hidden style={{ position: 'absolute', left: LABEL_W, top: 0, bottom: 0, width: trackW, pointerEvents: 'none', display: 'flex' }}>
        {dates.map((d) => (
          <div
            key={d}
            style={{
              width: W,
              flex: 'none',
              background: d === today ? 'var(--mantine-color-lagoon-light)' : weekday(d) >= 5 ? 'var(--mantine-color-default-hover)' : undefined,
            }}
          />
        ))}
      </div>

      {/* Header */}
      <div style={{ display: 'flex', position: 'sticky', top: 0, zIndex: 20, height: HEADER_H, background: 'var(--mantine-color-body)', borderBottom: '1px solid var(--mantine-color-default-border)' }}>
        <div style={{ width: LABEL_W, flex: 'none', position: 'sticky', left: 0, zIndex: 21, background: 'var(--mantine-color-body)', borderRight: '1px solid var(--mantine-color-default-border)' }} />
        {dates.map((d, i) => {
          const l = dayLabel(d, i18n.language);
          const showMonth = i === 0 || l.day === '1';
          return (
            <div key={d} style={{ width: W, flex: 'none', textAlign: 'center', paddingTop: 4, position: 'relative' }} data-date={d}>
              {showMonth && (
                <Text size="10px" c="dimmed" fw={600} tt="uppercase" style={{ position: 'absolute', left: 4, top: 2, whiteSpace: 'nowrap' }}>
                  {l.month}
                </Text>
              )}
              <Text size="xs" c={d === today ? 'lagoon' : 'dimmed'} mt={10} truncate>
                {l.weekday}
              </Text>
              <Text size="sm" fw={d === today ? 800 : 600} c={d === today ? 'lagoon' : undefined} className="hms-num">
                {l.day}
              </Text>
            </div>
          );
        })}
      </div>

      {rows.map((row) => {
        if (row.kind === 'group') {
          return (
            <div key={row.key} style={{ display: 'flex', position: 'relative', height: 30, borderBottom: '1px solid var(--mantine-color-default-border)', background: 'var(--mantine-color-default)' }}>
              <div style={{ width: LABEL_W, flex: 'none', position: 'sticky', left: 0, zIndex: 10, background: 'var(--mantine-color-default)', padding: '0 10px', display: 'flex', alignItems: 'center', gap: 6, borderRight: '1px solid var(--mantine-color-default-border)' }}>
                {row.type.color && <span style={{ width: 8, height: 8, borderRadius: 2, background: row.type.color, flex: 'none' }} />}
                <Text size="xs" fw={700} truncate>
                  {pickLocalized(row.type.name, i18n.language, hotel.default_language)}
                </Text>
              </div>
              {dates.map((d) => {
                const n = row.nights.get(d);
                const avail = n?.available ?? 0;
                return (
                  <Tooltip key={d} label={t('calendar.availability_hint', { available: avail, total: n?.total ?? 0 })} openDelay={500}>
                    <div
                      style={{
                        width: W,
                        flex: 'none',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 12,
                        fontWeight: 700,
                        color: avail < 0 ? 'var(--mantine-color-white)' : avail === 0 ? 'var(--mantine-color-orange-7)' : 'var(--mantine-color-dimmed)',
                        background: avail < 0 ? 'var(--mantine-color-red-6)' : undefined,
                      }}
                      className="hms-num"
                    >
                      {avail}
                    </div>
                  </Tooltip>
                );
              })}
            </div>
          );
        }
        const isRoom = row.kind === 'room';
        const dropValue = isRoom ? row.room.id : '';
        const isTarget = drag?.active && drag.targetRoom !== undefined && (drag.targetRoom ?? '') === dropValue && (isRoom || row.type.id === drag.item.room_type_id);
        return (
          <div key={row.key} data-room-number={isRoom ? row.room.number : undefined} style={{ display: 'flex', height: ROW_H, borderBottom: '1px solid var(--mantine-color-default-border)' }}>
            <div
              style={{
                width: LABEL_W,
                flex: 'none',
                position: 'sticky',
                left: 0,
                zIndex: 10,
                background: 'var(--mantine-color-body)',
                padding: '0 10px',
                display: 'flex',
                alignItems: 'center',
                borderRight: '1px solid var(--mantine-color-default-border)',
              }}
            >
              {isRoom ? (
                <Group gap={6} wrap="nowrap">
                  <Text fw={700} size="sm" className="hms-num">
                    {row.room.number}
                  </Text>
                  {row.room.housekeeping_status === 'dirty' && (
                    <Tooltip label={t('rooms.hk.dirty')}>
                      <span style={{ width: 6, height: 6, borderRadius: 3, background: 'var(--mantine-color-orange-6)' }} />
                    </Tooltip>
                  )}
                </Group>
              ) : (
                <Text size="xs" c="orange.7" fw={600}>
                  {t('calendar.unassigned')}
                </Text>
              )}
            </div>
            <div
              data-drop-row={dropValue}
              style={{
                position: 'relative',
                width: trackW,
                flex: 'none',
                backgroundImage: trackBackground,
                outline: isTarget ? '2px solid var(--mantine-color-lagoon-5)' : undefined,
                outlineOffset: -2,
                cursor: isRoom && props.canCreate ? 'copy' : undefined,
              }}
              onClick={(e) => {
                if (!isRoom || !props.canCreate || e.target !== e.currentTarget) return;
                const idx = Math.floor((e.clientX - e.currentTarget.getBoundingClientRect().left) / W);
                if (idx >= 0 && idx < days) props.onCreate(row.room, dates[idx]);
              }}
            >
              {row.items.map((it) => renderBar(it, isRoom ? row.room.id : null))}
            </div>
          </div>
        );
      })}
    </Box>
  );
}

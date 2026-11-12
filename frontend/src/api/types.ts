/** Types mirroring the backend's response schemas (snake_case, money as strings). */
import type { LocalizedText } from '@/lib/localized';

export type UUID = string;

export interface User {
  id: UUID;
  email: string;
  full_name: string;
  preferred_language: string;
  is_superadmin: boolean;
  totp_enabled: boolean;
  last_login_at: string | null;
}

export interface HotelAccess {
  id: UUID;
  code: string;
  name: string;
  timezone: string;
  currency_code: string;
  default_language: string;
  permissions: string[];
}

export interface Me {
  user: User;
  hotels: HotelAccess[];
  csrf_token: string;
  session_id: UUID;
}

export interface Hotel {
  id: UUID;
  organization_id: UUID;
  code: string;
  name: string;
  legal_name: string | null;
  description: LocalizedText;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country_code: string | null;
  latitude: string | null;
  longitude: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  social_links: Record<string, string>;
  timezone: string;
  default_language: string;
  supported_languages: string[];
  currency_code: string;
  check_in_time: string;
  check_out_time: string;
  tax_id: string | null;
  billing_info: {
    legal_address?: string | null;
    bank_details?: string | null;
    invoice_footer?: LocalizedText;
    invoice_prefix?: string | null;
    receipt_prefix?: string | null;
  };
  policies: { cancellation?: LocalizedText; payment?: LocalizedText; house_rules?: LocalizedText };
  is_active: boolean;
  version: number;
  updated_at: string;
}

export interface Building {
  id: UUID;
  code: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface Floor {
  id: UUID;
  building_id: UUID;
  level: number;
  name: string;
  sort_order: number;
  version: number;
}

export interface Amenity {
  id: UUID;
  code: string;
  name: LocalizedText;
  icon: string | null;
  scope: 'room' | 'hotel';
  sort_order: number;
  is_active: boolean;
  version: number;
}

export type BedType = 'single' | 'double' | 'queen' | 'king' | 'twin' | 'sofa_bed' | 'bunk' | 'crib';
export interface BedItem {
  type: BedType;
  count: number;
}

export interface RoomType {
  id: UUID;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  base_occupancy: number;
  max_occupancy: number;
  max_adults: number;
  max_children: number;
  bed_configuration: BedItem[];
  size_sqm: string | null;
  base_price: string;
  extra_adult_price: string;
  extra_child_price: string;
  color: string | null;
  sort_order: number;
  is_active: boolean;
  version: number;
  amenity_ids: UUID[];
  room_count: number;
}

export type BathroomType = 'private_shower' | 'private_bathtub' | 'private_shower_bathtub' | 'shared';

export interface Room {
  id: UUID;
  room_type_id: UUID;
  building_id: UUID | null;
  floor_id: UUID | null;
  number: string;
  name: string | null;
  max_occupancy: number | null;
  bed_configuration: BedItem[] | null;
  size_sqm: string | null;
  bathroom: BathroomType | null;
  has_balcony: boolean;
  view: string | null;
  base_price: string | null;
  housekeeping_status: 'clean' | 'dirty' | 'in_progress' | 'inspected';
  notes: string | null;
  sort_order: number;
  is_active: boolean;
  version: number;
  amenity_ids: UUID[];
}

export interface Facility {
  id: UUID;
  code: string;
  category: string;
  name: LocalizedText;
  description: LocalizedText;
  opening_hours: Record<string, [string, string][]>;
  is_available: boolean;
  pricing_mode: 'free' | 'paid' | 'on_request';
  price: string | null;
  price_unit: string | null;
  conditions: LocalizedText;
  notes: string | null;
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface Service {
  id: UUID;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  facility_id: UUID | null;
  price: string;
  pricing_unit: string;
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface TaxRate {
  id: UUID;
  code: string;
  name: LocalizedText;
  kind: 'percent' | 'fixed_per_night' | 'fixed_per_person_night';
  rate: string;
  is_inclusive: boolean;
  applies_to: 'accommodation' | 'services' | 'all';
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface AdminUser {
  id: UUID;
  email: string;
  full_name: string;
  preferred_language: string;
  is_active: boolean;
  is_superadmin: boolean;
  totp_enabled: boolean;
  last_login_at: string | null;
  locked_until: string | null;
  version: number;
  role_ids: UUID[];
  active_sessions: number;
}

export interface Role {
  id: UUID;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  version: number;
  permissions: string[];
  user_count: number;
}

export interface PermissionGroup {
  group: string;
  permissions: string[];
}

export interface ConnectedSession {
  id: UUID;
  user_id: UUID;
  user_email: string;
  user_full_name: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  ip: string | null;
  user_agent: string | null;
  device_label: string | null;
  online: boolean;
  current: boolean;
}

export interface MySession {
  id: UUID;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  ip: string | null;
  user_agent: string | null;
  device_label: string | null;
  current: boolean;
}

export interface AuditEntry {
  id: number;
  at: string;
  user_id: UUID | null;
  source: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  changes: Record<string, [unknown, unknown]> | null;
  ip: string | null;
}

export interface LoginEvent {
  id: number;
  at: string;
  user_id: UUID | null;
  email: string;
  success: boolean;
  reason: string | null;
  ip: string | null;
  user_agent: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

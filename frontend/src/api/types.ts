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
  applies_to: 'accommodation' | 'services' | 'food_beverage' | 'all';
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

// --- Guests -------------------------------------------------------------------

export interface Guest {
  id: UUID;
  first_name: string;
  last_name: string;
  email: string | null;
  phone: string | null;
  nationality: string | null;
  preferred_language: string | null;
  address: string | null;
  city: string | null;
  country_code: string | null;
  vip_level: number;
  tags: string[];
  preferences: Record<string, unknown>;
  notes: string | null;
  marketing_consent: boolean;
  version: number;
  created_at: string;
  date_of_birth: string | null;
  id_document_type: string | null;
  id_document_number: string | null;
  id_document_country: string | null;
  id_document_expiry: string | null;
  has_id_document: boolean;
}

export interface GuestDuplicate {
  guest: Guest;
  reasons: ('same_email' | 'same_phone' | 'similar_name')[];
  score: number;
}

// --- Reservations ---------------------------------------------------------------

export type ReservationStatus = 'pending' | 'confirmed' | 'checked_in' | 'checked_out' | 'cancelled' | 'no_show';
export type ReservationSource = 'direct' | 'website' | 'booking_com' | 'agoda' | 'walk_in' | 'phone' | 'email' | 'other';

export interface Night {
  night: string;
  price: string;
  price_source: string;
}

export interface ReservationRoom {
  id: UUID;
  room_type_id: UUID;
  room_id: UUID | null;
  rate_plan_id: UUID | null;
  arrival: string;
  departure: string;
  adults: number;
  children: number;
  occupies_inventory: boolean;
  accommodation_total: string;
  checked_in_at: string | null;
  checked_out_at: string | null;
  nights: Night[];
}

export interface TaxLine {
  code: string;
  name: Record<string, string>;
  kind: string;
  rate: string;
  is_inclusive: boolean;
  amount: string;
}

export interface Reservation {
  id: UUID;
  code: string;
  status: ReservationStatus;
  source: ReservationSource;
  external_ref: string | null;
  arrival: string;
  departure: string;
  adults: number;
  children: number;
  currency: string;
  accommodation_total: string;
  charges_total: string;
  tax_total: string;
  grand_total: string;
  paid_total: string;
  balance: string;
  tax_breakdown: TaxLine[];
  is_overbooked: boolean;
  is_modified: boolean;
  special_requests: string | null;
  internal_notes: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  booker: { id: UUID; first_name: string; last_name: string; email: string | null; phone: string | null; nationality: string | null; vip_level: number };
  rooms: ReservationRoom[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ReservationListItem {
  id: UUID;
  code: string;
  status: ReservationStatus;
  source: ReservationSource;
  arrival: string;
  departure: string;
  adults: number;
  children: number;
  guest_name: string;
  room_numbers: string[];
  room_count: number;
  grand_total: string;
  balance: string;
  currency: string;
  is_overbooked: boolean;
}

export interface ReservationEvent {
  id: number;
  at: string;
  user_id: UUID | null;
  user_name: string | null;
  source: string;
  action: string;
  details: Record<string, unknown>;
}

export interface Quote {
  currency: string;
  stays: { rate_plan_id: UUID; issues: RestrictionIssue[] }[];
  accommodation_total: string;
  tax_total: string;
  grand_total: string;
  taxes: TaxLine[];
  rooms: Night[][];
}

export interface AvailabilityNight {
  night: string;
  total: number;
  available: number;
}

export interface Availability {
  room_type_id: UUID;
  nights: AvailabilityNight[];
}

export interface AvailableRoom {
  id: UUID;
  number: string;
  name: string | null;
  room_type_id: UUID;
  max_occupancy: number | null;
}

export interface CalendarItem {
  kind: 'stay' | 'block';
  id: UUID;
  room_id: UUID | null;
  room_type_id: UUID | null;
  start: string;
  end: string;
  reservation_id: UUID | null;
  code: string | null;
  guest_name: string | null;
  status: ReservationStatus | null;
  adults: number | null;
  children: number | null;
  block_reason: string | null;
}

export interface CalendarData {
  start: string;
  end: string;
  items: CalendarItem[];
  unassigned: CalendarItem[];
  availability: Availability[];
}

export interface RoomBlock {
  id: UUID;
  room_id: UUID;
  start_date: string;
  end_date: string;
  reason: 'maintenance' | 'out_of_service' | 'owner_use' | 'other';
  notes: string | null;
}

// --- Pricing ------------------------------------------------------------------------

export type MealPlan = 'room_only' | 'breakfast' | 'half_board' | 'full_board' | 'all_inclusive';
export type RuleKind = 'season' | 'weekday' | 'occupancy' | 'long_stay' | 'last_minute' | 'early_bird';

export interface RatePlan {
  id: UUID;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  meal_plan: MealPlan;
  is_refundable: boolean;
  cancellation_policy_id: UUID | null;
  parent_rate_plan_id: UUID | null;
  derive_mode: 'percent' | 'amount' | 'amount_per_person' | null;
  derive_value: string | null;
  room_type_ids: UUID[];
  valid_from: string | null;
  valid_to: string | null;
  min_advance_days: number | null;
  max_advance_days: number | null;
  is_default: boolean;
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface PricingRule {
  id: UUID;
  name: LocalizedText;
  kind: RuleKind;
  priority: number;
  date_from: string | null;
  date_to: string | null;
  weekdays: number[];
  room_type_ids: UUID[];
  rate_plan_ids: UUID[];
  adjustment: 'percent' | 'amount' | 'set';
  value: string;
  conditions: { min_nights?: number; max_days_before?: number; min_days_before?: number; min_occupancy?: number };
  is_active: boolean;
  version: number;
}

export interface CancellationPolicy {
  id: UUID;
  code: string;
  name: LocalizedText;
  description: LocalizedText;
  free_until_days: number | null;
  penalty_kind: 'percent' | 'nights';
  penalty_value: string;
  no_show_nights: number;
  is_active: boolean;
  version: number;
}

export interface GridCell {
  room_type_id: UUID;
  date: string;
  price: string;
  source: 'daily_rate' | 'derived' | 'base';
  explicit: boolean;
  min_stay: number | null;
  max_stay: number | null;
  closed: boolean;
  closed_to_arrival: boolean;
  closed_to_departure: boolean;
  restrictions_inherited: boolean;
  available: number;
}

export interface RateGrid {
  rate_plan_id: UUID;
  start: string;
  end: string;
  room_type_ids: UUID[];
  cells: GridCell[];
}

export interface RestrictionIssue {
  code: string;
  [key: string]: unknown;
}

export interface Offer {
  room_type_id: UUID;
  rate_plan_id: UUID;
  total: string;
  average_night: string;
  nights: { night: string; price: string; price_source: string }[];
  available: number;
  issues: RestrictionIssue[];
  bookable: boolean;
}

// --- front desk & billing (phase 5) ------------------------------------------

export type ChargeKind = 'service' | 'fee' | 'adjustment' | 'outlet';
export type FeeType = 'cancellation' | 'no_show' | 'early_departure' | 'late_checkout' | 'damage' | 'other';
export type PaymentKind = 'payment' | 'deposit' | 'refund';
export type PaymentMethod = 'cash' | 'card' | 'bank_transfer' | 'online' | 'other';
export type CardBrand = 'visa' | 'mastercard' | 'amex' | 'unionpay' | 'jcb' | 'discover' | 'other';
export type HousekeepingStatus = 'clean' | 'dirty' | 'in_progress' | 'inspected';

export interface Currency {
  id: UUID;
  code: string;
  units_per_base: string;
  is_active: boolean;
  version: number;
  updated_at: string;
}

export interface FolioCharge {
  id: UUID;
  reservation_room_id: UUID | null;
  kind: ChargeKind;
  fee_type: FeeType | null;
  service_id: UUID | null;
  name: LocalizedText;
  description: string | null;
  service_date: string;
  quantity: string;
  unit_price: string;
  amount: string;
  tax_amount: string;
  is_void: boolean;
  void_reason: string | null;
  voided_at: string | null;
  voided_by_name: string | null;
  created_by_name: string | null;
  created_at: string;
}

export interface Payment {
  id: UUID;
  number: string;
  kind: PaymentKind;
  method: PaymentMethod;
  amount: string;
  currency: string;
  exchange_rate: string;
  amount_base: string;
  reference: string | null;
  card_brand: CardBrand | null;
  card_last4: string | null;
  notes: string | null;
  received_at: string;
  received_by_name: string | null;
  is_void: boolean;
  void_reason: string | null;
  voided_at: string | null;
  voided_by_name: string | null;
}

export interface PaymentListItem extends Payment {
  reservation_id: UUID;
  reservation_code: string;
  guest_name: string;
}

export interface PaymentReport {
  items: PaymentListItem[];
  total: number;
  limit: number;
  offset: number;
  summary: { method: PaymentMethod; currency: string; kind: PaymentKind; count: number; amount: string; amount_base: string }[];
  net_base: string;
}

export interface Invoice {
  id: UUID;
  reservation_id: UUID;
  number: string;
  status: 'issued' | 'void';
  issue_date: string;
  language: string;
  currency: string;
  bill_to: { name: string; company?: string; tax_id?: string; address?: string; city?: string; country_code?: string; email?: string };
  subtotal: string;
  tax_total: string;
  total: string;
  paid_total: string;
  balance: string;
  void_reason: string | null;
  voided_at: string | null;
  created_at: string;
}

export interface InvoiceListItem extends Invoice {
  reservation_code: string;
}

export interface AccommodationRun {
  reservation_room_id: UUID;
  room_type_id: UUID;
  room_id: UUID | null;
  rate_plan_id: UUID | null;
  start: string;
  end: string;
  nights: number;
  unit_price: string;
  amount: string;
}

export interface Folio {
  reservation_id: UUID;
  version: number;
  currency: string;
  accommodation: AccommodationRun[];
  charges: FolioCharge[];
  payments: Payment[];
  taxes: TaxLine[];
  totals: { accommodation: string; charges: string; tax_total: string; grand_total: string; paid_total: string; balance: string };
  invoices: Invoice[];
  invoice_outdated: boolean;
}

export interface FeePreview {
  action: 'cancel' | 'no_show';
  currency: string;
  fee: string;
  stays: { reservation_room_id: UUID; rate_plan_id: UUID | null; policy_id: UUID | null; refundable: boolean; free_until: string | null; stay_total: string; fee: string }[];
}

export interface StayRow {
  reservation_id: UUID;
  code: string;
  status: ReservationStatus;
  version: number;
  reservation_room_id: UUID;
  guest_id: UUID;
  guest_name: string;
  vip_level: number;
  room_id: UUID | null;
  room_number: string | null;
  room_type_id: UUID;
  housekeeping_status: HousekeepingStatus | null;
  arrival: string;
  departure: string;
  adults: number;
  children: number;
  checked_in_at: string | null;
  checked_out_at: string | null;
  balance: string;
  currency: string;
  special_requests: string | null;
  flags: ('late_arrival' | 'overdue')[];
}

export interface FrontDesk {
  date: string;
  is_today: boolean;
  arrivals: StayRow[];
  departures: StayRow[];
  in_house: StayRow[];
}

export interface RoomBoardRow {
  room_id: UUID;
  number: string;
  room_type_id: UUID;
  floor_id: UUID | null;
  housekeeping_status: HousekeepingStatus;
  version: number;
  block: { id: UUID; reason: string; start_date: string; end_date: string } | null;
  occupant: StayRow | null;
  arriving: StayRow | null;
  departing: boolean;
  tasks: { id: UUID; task_type: TaskType; status: TaskStatus; priority: Priority; assigned_to: UUID | null; assigned_to_name: string | null; version: number }[];
  maintenance: { open: number; priority: Priority } | null;
}

// --- housekeeping & maintenance (phase 5) -------------------------------------

export type TaskType = 'departure' | 'stayover' | 'deep_clean' | 'touch_up' | 'inspection';
export type TaskStatus = 'pending' | 'in_progress' | 'done' | 'inspected' | 'skipped';
export type Priority = 'low' | 'normal' | 'high' | 'urgent';

export interface HousekeepingTask {
  id: UUID;
  room_id: UUID;
  room_number: string;
  room_type_id: UUID;
  task_date: string;
  task_type: TaskType;
  priority: Priority;
  status: TaskStatus;
  source: string;
  assigned_to: UUID | null;
  assigned_to_name: string | null;
  reservation_room_id: UUID | null;
  notes: string | null;
  skip_reason: string | null;
  started_at: string | null;
  completed_at: string | null;
  completed_by_name: string | null;
  inspected_at: string | null;
  inspected_by_name: string | null;
  room_status: HousekeepingStatus;
  arrival_today: boolean;
  version: number;
}

export interface StaffMember {
  id: UUID;
  full_name: string;
}

export type MaintenanceCategory = 'plumbing' | 'electrical' | 'air_conditioning' | 'furniture' | 'appliance' | 'building' | 'it_network' | 'pest_control' | 'other';
export type MaintenanceStatus = 'reported' | 'in_progress' | 'on_hold' | 'completed' | 'cancelled';

export interface MaintenanceRequest {
  id: UUID;
  number: string;
  room_id: UUID | null;
  room_number: string | null;
  facility_id: UUID | null;
  location: string | null;
  category: MaintenanceCategory;
  priority: Priority;
  title: string;
  description: string | null;
  status: MaintenanceStatus;
  assigned_to: UUID | null;
  assigned_to_name: string | null;
  reported_by_name: string | null;
  block: { id: UUID; start_date: string; end_date: string } | null;
  started_at: string | null;
  completed_at: string | null;
  resolution: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface MaintenanceDetail extends MaintenanceRequest {
  updates: { id: number; at: string; user_name: string | null; action: string; comment: string | null; details: Record<string, unknown> }[];
}

// --- restaurant & bar ------------------------------------------------------------

export type OutletKind = 'restaurant' | 'bar' | 'cafe' | 'room_service' | 'other';
export type Station = 'kitchen' | 'bar' | 'none';
export type OrderType = 'dine_in' | 'takeaway' | 'room_service';
export type LineStatus = 'new' | 'sent' | 'preparing' | 'ready' | 'served' | 'void';
export type PosMethod = 'cash' | 'card' | 'bank_transfer' | 'online' | 'other' | 'room_charge';

export interface Outlet {
  id: UUID;
  code: string;
  name: LocalizedText;
  kind: OutletKind;
  facility_id: UUID | null;
  service_charge_percent: string;
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface MenuCategory {
  id: UUID;
  outlet_id: UUID;
  name: LocalizedText;
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface MenuItem {
  id: UUID;
  outlet_id: UUID;
  category_id: UUID;
  code: string | null;
  name: LocalizedText;
  description: LocalizedText;
  price: string;
  station: Station;
  is_available: boolean;
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface DiningTable {
  id: UUID;
  outlet_id: UUID;
  label: string;
  area: string | null;
  seats: number;
  sort_order: number;
  is_active: boolean;
  version: number;
}

export interface GuestRef {
  reservation_room_id: UUID;
  reservation_id: UUID;
  reservation_code: string;
  room_number: string | null;
  guest_name: string;
  in_house: boolean;
}

export interface OrderSummary {
  id: UUID;
  outlet_id: UUID;
  number: string;
  business_date: string;
  table_id: UUID | null;
  table_label: string | null;
  order_type: OrderType;
  covers: number;
  status: 'open' | 'closed' | 'cancelled';
  total: string;
  paid_total: string;
  balance: string;
  lines_new: number;
  lines_waiting: number;
  lines_ready: number;
  opened_at: string;
  opened_by_name: string | null;
  guest: GuestRef | null;
  version: number;
}

export interface OrderLine {
  id: UUID;
  menu_item_id: UUID | null;
  name: LocalizedText;
  station: Station;
  unit_price: string;
  quantity: number;
  amount: string;
  notes: string | null;
  status: LineStatus;
  created_at: string;
  sent_at: string | null;
  ready_at: string | null;
  served_at: string | null;
  void_reason: string | null;
}

export interface OrderPayment {
  id: UUID;
  method: PosMethod;
  amount: string;
  currency: string;
  exchange_rate: string;
  amount_base: string;
  tendered: string | null;
  reference: string | null;
  card_brand: string | null;
  card_last4: string | null;
  room_number: string | null;
  received_at: string;
  received_by_name: string | null;
  is_void: boolean;
  void_reason: string | null;
}

export interface RestaurantOrder extends OrderSummary {
  discount_kind: 'percent' | 'amount' | null;
  discount_value: string | null;
  discount_reason: string | null;
  subtotal: string;
  discount_total: string;
  service_charge: string;
  service_charge_percent: string;
  tax_total: string;
  tax_breakdown: TaxLine[];
  notes: string | null;
  closed_at: string | null;
  cancel_reason: string | null;
  lines: OrderLine[];
  payments: OrderPayment[];
  change_due: string | null;
}

export interface FloorTable {
  id: UUID;
  label: string;
  area: string | null;
  seats: number;
  order: OrderSummary | null;
}

export interface KitchenTicket {
  order_id: UUID;
  number: string;
  table_label: string | null;
  order_type: OrderType;
  covers: number;
  room_number: string | null;
  lines: OrderLine[];
}

export interface BreakfastRow {
  reservation_room_id: UUID;
  reservation_code: string;
  room_number: string | null;
  guest_name: string;
  adults: number;
  children: number;
  meal_plan: string;
  served_covers: number | null;
}

export interface SalesReport {
  start: string;
  end: string;
  orders: number;
  covers: number;
  subtotal: string;
  discounts: string;
  service_charge: string;
  taxes: string;
  total: string;
  average_check: string;
  voided_lines: number;
  voided_amount: string;
  by_category: { category_id: UUID | null; name: LocalizedText; quantity: number; amount: string }[];
  top_items: { menu_item_id: UUID | null; name: LocalizedText; quantity: number; amount: string }[];
  by_method: { method: PosMethod; currency: string; count: number; amount: string; amount_base: string }[];
}

// --- vehicle rental -----------------------------------------------------------------

export type VehicleKind = 'scooter' | 'motorbike' | 'car' | 'van' | 'bicycle' | 'e_bike' | 'tuk_tuk' | 'boat' | 'other';
export type RentalStatus = 'reserved' | 'out' | 'returned' | 'cancelled' | 'no_show';
export type DepositKind = 'none' | 'cash' | 'card_hold' | 'passport' | 'id_card' | 'other';

export interface Vehicle {
  id: UUID;
  code: string;
  plate: string | null;
  kind: VehicleKind;
  make: string | null;
  model: string | null;
  color: string | null;
  year: number | null;
  seats: number;
  transmission: 'manual' | 'automatic' | null;
  daily_rate: string;
  hourly_rate: string | null;
  driver_daily_rate: string | null;
  deposit_amount: string;
  odometer: number;
  status: 'available' | 'maintenance' | 'retired';
  insurance_expiry: string | null;
  registration_expiry: string | null;
  notes: string | null;
  sort_order: number;
  version: number;
  available: boolean | null;
  unavailable_reason: string | null;
  document_warning: string | null;
}

export interface RentalQuote {
  hours: number;
  charge_days: number;
  base_amount: string;
  driver_amount: string;
  subtotal: string;
  tax_total: string;
  total: string;
  deposit_amount: string;
}

export interface Rental {
  id: UUID;
  number: string;
  vehicle_id: UUID;
  vehicle_code: string;
  vehicle_label: string;
  vehicle_kind: VehicleKind;
  vehicle_odometer: number;
  guest_id: UUID;
  guest_name: string;
  guest_phone: string | null;
  reservation_room_id: UUID | null;
  room_number: string | null;
  in_house: boolean;
  status: RentalStatus;
  start_at: string;
  end_at: string;
  picked_up_at: string | null;
  returned_at: string | null;
  overdue: boolean;
  with_driver: boolean;
  licence_required: boolean;
  licence_last4: string | null;
  licence_country: string | null;
  licence_expiry: string | null;
  odometer_out: number | null;
  odometer_in: number | null;
  fuel_out: number | null;
  fuel_in: number | null;
  condition_out: string | null;
  condition_in: string | null;
  deposit_kind: DepositKind;
  deposit_amount: string | null;
  deposit_currency: string | null;
  deposit_note: string | null;
  deposit_returned_at: string | null;
  base_amount: string;
  driver_amount: string;
  late_fee: string;
  fuel_charge: string;
  damage_charge: string;
  damage_note: string | null;
  discount_amount: string;
  discount_reason: string | null;
  subtotal: string;
  tax_total: string;
  tax_breakdown: TaxLine[];
  total: string;
  paid_total: string;
  balance: string;
  notes: string | null;
  cancel_reason: string | null;
  created_at: string;
  version: number;
  payments: OrderPayment[];
  change_due: string | null;
}

// --- Channel manager ---------------------------------------------------------

export type ChannelState = 'credentials_saved' | 'test_ok' | 'live' | 'degraded' | 'paused';

export interface ChannelStatus {
  state: ChannelState;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_message: string | null;
  last_push_at: string | null;
  last_pull_at: string | null;
  last_error_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  next_push_at: string | null;
  next_pull_at: string | null;
  horizon_end: string | null;
  full_refresh_requested: boolean;
  last_full_refresh_at: string | null;
  products_fetched_at: string | null;
}

export interface ChannelConnection {
  id: UUID;
  provider: 'siteminder';
  name: string;
  environment: 'test' | 'production';
  endpoint_url: string | null;
  account_code: string;
  username: string;
  hotel_code: string;
  enabled: boolean;
  push_ari: boolean;
  pull_reservations: boolean;
  horizon_days: number;
  pull_interval_seconds: number;
  settings: { rate_amount?: 'after_tax' | 'before_tax'; rest_base_url?: string };
  version: number;
  created_at: string;
  status: ChannelStatus;
  pending_changes: number;
  unmapped_room_types: number;
  mapped_rates: number;
  bookings_attention: number;
  errors_24h: number;
}

export interface ChannelProduct {
  room_code: string;
  room_name: string | null;
  rate_code: string | null;
  rate_name: string | null;
  included_occupancy: number | null;
}

export interface ChannelMappings {
  rooms: { room_type_id: UUID; external_code: string }[];
  rates: { room_type_id: UUID; rate_plan_id: UUID; external_code: string }[];
  products: ChannelProduct[];
  products_fetched_at: string | null;
  unknown_codes: string[];
}

export interface ChannelMessage {
  id: number;
  at: string;
  operation: string;
  outcome: 'ok' | 'warning' | 'error';
  http_status: number | null;
  duration_ms: number | null;
  summary: string | null;
}

export interface ChannelMessageDetail extends ChannelMessage {
  request_body: string | null;
  response_body: string | null;
}

export interface ChannelBooking {
  id: UUID;
  connection_id: UUID;
  connection_name: string;
  external_id: string;
  revision: string;
  action: 'book' | 'modify' | 'cancel';
  channel_name: string | null;
  message_at: string | null;
  received_at: string;
  import_status: 'pending' | 'imported' | 'failed' | 'ignored';
  error_code: string | null;
  error_detail: string | null;
  reservation_id: UUID | null;
  reservation_code: string | null;
  overbooked: boolean;
  attempts: number;
  confirmed_at: string | null;
  card_brand: string | null;
  card_last4: string | null;
  guest_name: string | null;
  arrival: string | null;
  departure: string | null;
  total: string | null;
  currency: string | null;
}

// --- Reports -------------------------------------------------------------------

/** Ratios are null when the denominator is zero; amounts are null without reports.financial. */
export interface Kpis {
  rooms: number;
  out_of_service: number;
  available: number;
  sold: number;
  occupancy: string | null;
  revenue: string | null;
  adr: string | null;
  revpar: string | null;
}

export interface DailyKpis extends Kpis {
  date: string;
}

export interface BookingStats {
  created: number;
  cancelled: number;
  cancellation_rate: string | null;
  arrivals: number;
  no_shows: number;
  no_show_rate: string | null;
  average_stay: string | null;
  average_lead_days: string | null;
}

export interface ShareRow {
  sold: number;
  share: string | null;
  revenue: string | null;
  revenue_share: string | null;
  adr: string | null;
}

export interface OtherRevenue {
  services: string;
  fees: string;
  adjustments: string;
  restaurant: string;
  vehicles: string;
  total: string;
  restaurant_checks: number;
  rentals: number;
}

export interface PerformanceReport {
  start: string;
  end: string;
  currency: string;
  financial: boolean;
  totals: Kpis;
  bookings: BookingStats;
  daily: DailyKpis[];
  by_source: (ShareRow & { source: string })[];
  by_rate_plan: (ShareRow & { rate_plan_id: UUID | null })[];
  by_room_type: (Kpis & { room_type_id: UUID })[];
  other_revenue: OtherRevenue | null;
  compare: {
    kind: 'previous' | 'last_year';
    start: string;
    end: string;
    totals: Kpis;
    bookings: BookingStats;
    daily: { date: string; occupancy: string | null; adr: string | null; revpar: string | null }[];
    other_revenue: OtherRevenue | null;
  } | null;
}

export interface ForecastReport {
  start: string;
  end: string;
  currency: string;
  financial: boolean;
  totals: Kpis & { pickup: number };
  daily: (DailyKpis & { pickup: number; pickup_revenue: string | null })[];
}

export interface TodayReport {
  date: string;
  currency: string;
  financial: boolean;
  tonight: Kpis;
  arrivals_due: number;
  arrived: number;
  departures_due: number;
  departed: number;
  in_house: number;
  month_to_date: Kpis;
  month_to_date_last_year: Kpis;
  next_days: { date: string; occupancy: string | null; sold: number; available: number }[];
}

// --- Backups (phase 10) ------------------------------------------------------

export type BackupTrigger = 'schedule' | 'manual' | 'safety' | 'cli' | 'unknown';

export interface BackupFile {
  file: string;
  created_at: string | null;
  bytes: number;
  sha256: string | null;
  verified_tables: number | null;
  verified_hotels: number | null;
  schema_version: string | null;
  trigger: BackupTrigger | string;
  requested_by: string | null;
  restorable: boolean;
}

export interface BackupRun {
  kind: 'backup' | 'restore' | string;
  request_id: string | null;
  trigger: string | null;
  requested_by: string | null;
  started_at: string | null;
  finished_at: string | null;
  status: 'ok' | 'failed' | string;
  error: string | null;
  file: string | null;
  safety_backup: string | null;
  bytes: number | null;
}

export interface BackupOperation {
  kind: 'backup' | 'restore' | string;
  step: string;
  request_id: string | null;
  requested_by: string | null;
  since: string | null;
}

export interface BackupRequest {
  id: string;
  kind: 'backup' | 'restore' | string;
  file: string | null;
  requested_by: string | null;
  requested_at: string | null;
}

export interface BackupsStatus {
  service: {
    connected: boolean;
    running: boolean;
    last_seen: string | null;
    interval_hours: number | null;
    retention_days: number | null;
    last_scheduled: string | null;
    next_scheduled: string | null;
  };
  current: BackupOperation | null;
  pending: BackupRequest[];
  backups: BackupFile[];
  runs: BackupRun[];
  schema_version: string | null;
  restore: { allowed: boolean; reason: 'NOT_SUPERADMIN' | 'MULTI_ORGANIZATION' | null };
}

// --- End of day (night audit) ------------------------------------------------------

export interface AuditStay {
  reservation_id: UUID;
  code: string;
  version: number;
  status: string;
  source: string;
  guest_name: string;
  room_number: string | null;
  arrival: string;
  departure: string;
  balance: string;
  currency: string;
}

export interface NightAuditItems {
  not_arrived: AuditStay[];
  not_departed: AuditStay[];
  open_checks: { order_id: UUID; number: string; outlet: LocalizedText; table: string | null; order_type: string; business_date: string; total: string }[];
  overdue_rentals: { rental_id: UUID; number: string; vehicle: string; end_at: string }[];
  unassigned_tomorrow: AuditStay[];
  balances_due: { count: number; total: string; stays: AuditStay[] };
}

export interface DayReport {
  date: string;
  currency: string;
  rooms: { rooms: number; out_of_service: number; available: number; sold: number; occupancy: string | null; revenue: string | null; adr: string | null; revpar: string | null };
  movements: {
    arrivals: number;
    departures: number;
    walk_ins: number;
    no_shows: number;
    bookings_made: number;
    cancellations: number;
    arrivals_tomorrow: number;
    occupancy_tomorrow: string | null;
  };
  revenue: { rooms: string; restaurant: string; vehicles: string; services: string; fees: string; adjustments: string; total: string } | null;
  payments: { source: 'folio' | 'restaurant' | 'vehicles'; kind: string; method: string; currency: string; count: number; amount: string; amount_base: string }[];
  payments_by_method: { method: string; amount_base: string }[];
  payments_net: string | null;
  invoices: { issued: number; total: string; voided: number } | null;
}

export interface DayClosureInfo {
  id: UUID;
  date: string;
  closed_at: string;
  closed_by_name: string | null;
  notes: string | null;
  open_items: number;
}

export interface NightAudit {
  date: string;
  today: string;
  last_closed: string | null;
  can_close: boolean;
  blocker: 'ALREADY_CLOSED' | 'DAY_NOT_OVER' | 'PREVIOUS_DAY_OPEN' | null;
  closure: DayClosureInfo | null;
  report: DayReport;
  open_items: NightAuditItems;
  open_count: number;
}

export interface DayClosureRow extends DayClosureInfo {
  occupancy: string | null;
  sold: number | null;
  revenue: string | null;
  payments_net: string | null;
  currency: string;
}

// --- Photos and logos --------------------------------------------------------------

export type MediaOwnerType = 'hotel' | 'room_type' | 'facility' | 'maintenance_request';

export interface MediaFile {
  id: string;
  owner_type: MediaOwnerType;
  owner_id: string;
  kind: 'logo' | 'photo';
  filename: string;
  content_type: string;
  size: number;
  width: number;
  height: number;
  sort_order: number;
  uploaded_by: string | null;
  uploaded_by_name: string | null;
  created_at: string;
  url: string;
  thumbnail_url: string;
}

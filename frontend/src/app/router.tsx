import { lazy } from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router';
import { Center, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { AppLayout, PageLoader } from '@/app/AppLayout';
import { useAuth } from '@/auth/AuthProvider';
import { LoginPage } from '@/auth/LoginPage';

const DashboardPage = lazy(() => import('@/modules/dashboard/DashboardPage'));
const RoomsPage = lazy(() => import('@/modules/rooms/RoomsPage'));
const ReservationsPage = lazy(() => import('@/modules/reservations/ReservationsPage'));
const ReservationDetailPage = lazy(() => import('@/modules/reservations/ReservationDetailPage'));
const CalendarPage = lazy(() => import('@/modules/calendar/CalendarPage'));
const GuestsPage = lazy(() => import('@/modules/guests/GuestsPage'));
const PricingPage = lazy(() => import('@/modules/pricing/PricingPage'));
const ChannelsPage = lazy(() => import('@/modules/channels/ChannelsPage'));
const FrontDeskPage = lazy(() => import('@/modules/frontdesk/FrontDeskPage'));
const BillingPage = lazy(() => import('@/modules/billing/BillingPage'));
const HousekeepingPage = lazy(() => import('@/modules/housekeeping/HousekeepingPage'));
const MaintenancePage = lazy(() => import('@/modules/maintenance/MaintenancePage'));
const RestaurantPage = lazy(() => import('@/modules/restaurant/RestaurantPage'));
const RestaurantOrderPage = lazy(() => import('@/modules/restaurant/OrderPage'));
const VehiclesPage = lazy(() => import('@/modules/vehicles/VehiclesPage'));
const ServicesPage = lazy(() => import('@/modules/services/ServicesPage'));
const UsersPage = lazy(() => import('@/modules/users/UsersPage'));
const SettingsPage = lazy(() => import('@/modules/settings/SettingsPage'));
const AccountPage = lazy(() => import('@/modules/account/AccountPage'));

function NotFound() {
  const { t } = useTranslation();
  return (
    <Center h="50vh">
      <Stack align="center" gap={4}>
        <Title order={2}>404</Title>
        <Text c="dimmed">{t('common.page_not_found')}</Text>
      </Stack>
    </Center>
  );
}

function NoHotelAccess() {
  const { t } = useTranslation();
  const { logout } = useAuth();
  return (
    <Center h="100dvh">
      <Stack align="center" gap="xs" maw={420}>
        <Title order={3}>{t('auth.no_hotel_title')}</Title>
        <Text c="dimmed" ta="center">
          {t('auth.no_hotel_body')}
        </Text>
        <Text component="button" c="lagoon" onClick={() => void logout()} style={{ background: 'none', border: 0, cursor: 'pointer' }}>
          {t('auth.logout')}
        </Text>
      </Stack>
    </Center>
  );
}

const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'reservations', element: <ReservationsPage /> },
      { path: 'reservations/:id', element: <ReservationDetailPage /> },
      { path: 'calendar', element: <CalendarPage /> },
      { path: 'rooms', element: <RoomsPage /> },
      { path: 'guests', element: <GuestsPage /> },
      { path: 'pricing/*', element: <PricingPage /> },
      { path: 'channels', element: <ChannelsPage /> },
      { path: 'front-desk', element: <FrontDeskPage /> },
      { path: 'billing/*', element: <BillingPage /> },
      { path: 'housekeeping', element: <HousekeepingPage /> },
      { path: 'maintenance', element: <MaintenancePage /> },
      { path: 'restaurant/orders/:id', element: <RestaurantOrderPage /> },
      { path: 'restaurant/*', element: <RestaurantPage /> },
      { path: 'vehicles/*', element: <VehiclesPage /> },
      { path: 'services', element: <ServicesPage /> },
      { path: 'users/*', element: <UsersPage /> },
      { path: 'settings/*', element: <SettingsPage /> },
      { path: 'account', element: <AccountPage /> },
      { path: 'login', element: <Navigate to="/" replace /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export function AppRouter() {
  const { status, me } = useAuth();
  if (status === 'loading') return <PageLoader />;
  if (status === 'anonymous') return <LoginPage />;
  if (me && me.hotels.length === 0) return <NoHotelAccess />;
  return <RouterProvider router={router} />;
}

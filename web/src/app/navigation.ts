import type { PageName } from './pages';

export interface NavItem {
  to: string;
  label: string;
  page: PageName;
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Chat', page: 'chat' },
  { to: '/matches', label: 'Matches', page: 'matches' },
  { to: '/preferences', label: 'Preferences', page: 'preferences' },
  { to: '/search', label: 'Search', page: 'search' },
  { to: '/evals', label: 'Evals', page: 'evals' },
];

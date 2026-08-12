export interface AppNavItem {
  key: string;
  label: string;
  to: string;
  /** Optional short badge, e.g. an unread count. Zero is not rendered. */
  badge?: number;
  /** Marks an item that must be dealt with (safety, privacy, payment). */
  critical?: boolean;
  /** Exact-match highlighting instead of prefix matching. */
  exact?: boolean;
}

export interface AppNavGroup {
  key: string;
  label: string;
  /** Single-character or short glyph rendered in the collapsed rail. */
  glyph: string;
  to: string;
  items: AppNavItem[];
}

export interface AppTabItem {
  key: string;
  label: string;
  glyph: string;
  to: string;
  badge?: number;
}

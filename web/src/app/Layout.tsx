import { Suspense, useEffect, useRef } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router';

import { ProfileControls } from '../features/profile/ProfileControls';
import { PageSkeleton } from '../ui/Skeleton';
import { HealthBadge } from './HealthBadge';
import styles from './Layout.module.css';
import { NAV_ITEMS } from './navigation';
import { prefetchPage } from './pages';
import { StatusBanner } from './StatusBanner';

export function Layout() {
  const mainRef = useRef<HTMLElement>(null);
  const { pathname } = useLocation();
  const previousPath = useRef(pathname);

  // After a client-side navigation, move focus to the new page's content, as a full page load
  // would. Otherwise keyboard and screen-reader users are left on the link they just pressed.
  useEffect(() => {
    if (previousPath.current === pathname) return; // first render (and StrictMode's re-run)
    previousPath.current = pathname;
    mainRef.current?.focus();
  }, [pathname]);

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main">
        Skip to content
      </a>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link to="/" className={styles.brand}>
            Matchwise
          </Link>
          <div className={styles.health}>
            <HealthBadge />
          </div>
          <nav aria-label="Main" className={styles.nav}>
            <ul className={styles.navList}>
              {NAV_ITEMS.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) =>
                      isActive ? `${styles.navLink} ${styles.active}` : styles.navLink
                    }
                    onMouseEnter={() => {
                      prefetchPage(item.page);
                    }}
                    onFocus={() => {
                      prefetchPage(item.page);
                    }}
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <StatusBanner />
      <main id="main" ref={mainRef} tabIndex={-1} className={styles.main}>
        <Suspense fallback={<PageSkeleton />}>
          <Outlet />
        </Suspense>
      </main>
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <ProfileControls />
        </div>
      </footer>
    </div>
  );
}

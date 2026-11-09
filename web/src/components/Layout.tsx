import { NavLink, Outlet, useMatches } from "react-router";
import type { RouteHandle } from "../routes";
import styles from "./Layout.module.css";

const LINKS = [
  { to: "/", label: "Map" },
  { to: "/accuracy", label: "Accuracy" },
  { to: "/about", label: "About" },
];

export function Layout() {
  const fullBleed = useMatches().some(
    (match) => (match.handle as RouteHandle | undefined)?.fullBleed,
  );
  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <NavLink to="/" className={styles.wordmark}>
          AirSight
        </NavLink>
        <nav aria-label="Main">
          <ul className={styles.nav}>
            {LINKS.map((link) => (
              <li key={link.to}>
                <NavLink
                  to={link.to}
                  end
                  className={({ isActive }) =>
                    isActive ? `${styles.link} ${styles.active}` : styles.link
                  }
                >
                  {link.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main className={fullBleed ? styles.fullBleed : styles.main}>
        <Outlet />
      </main>
      <footer className={fullBleed ? styles.footnote : styles.footer}>
        <p>
          Corrected PurpleAir readings, checked against official AirNow
          monitors. Not for regulatory use.
        </p>
      </footer>
    </div>
  );
}

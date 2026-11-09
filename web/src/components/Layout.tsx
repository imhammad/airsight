import { NavLink, Outlet } from "react-router";
import styles from "./Layout.module.css";

const LINKS = [
  { to: "/", label: "Nearby" },
  { to: "/accuracy", label: "Accuracy" },
  { to: "/about", label: "About" },
];

export function Layout() {
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
      <main className={styles.main}>
        <Outlet />
      </main>
      <footer className={styles.footer}>
        <p>
          Corrected PurpleAir readings, checked against official AirNow
          monitors. Not for regulatory use.
        </p>
      </footer>
    </div>
  );
}

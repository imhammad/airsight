import { NavLink } from "react-router";

export function NotFoundPage() {
  return (
    <section>
      <h1>Page not found</h1>
      <p style={{ marginTop: 8 }}>
        <NavLink to="/">Back to the air near you</NavLink>
      </p>
    </section>
  );
}

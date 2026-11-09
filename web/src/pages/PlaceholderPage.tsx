/** A page that is planned but not built yet, so navigation works from day one. */
export function PlaceholderPage({
  title,
  issue,
}: {
  title: string;
  issue: number;
}) {
  return (
    <section>
      <h1>{title}</h1>
      <p style={{ marginTop: 8, color: "var(--secondary)" }}>
        Coming soon (#{issue}).
      </p>
    </section>
  );
}

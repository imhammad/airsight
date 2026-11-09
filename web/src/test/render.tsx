import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { routes } from "../routes";

/** Render the app at a path, with a fresh cache and no retries. */
export function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

/** Make every fetch answer with this status and JSON body. */
export function answerWith(
  status: number,
  body: unknown,
  contentType = "application/json",
) {
  const fetchMock = vi.fn<typeof fetch>(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": contentType },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Answer each fetch by its path, such as "/v1/sensors/pa-1"; anything else is a 404. */
export function answerByPath(answers: Record<string, [number, unknown]>) {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const { pathname } = new URL(String(input));
    const [status, body] = answers[pathname] ?? [
      404,
      {
        type: "about:blank",
        title: "Not Found",
        status: 404,
        detail: "Not found",
      },
    ];
    return new Response(JSON.stringify(body), {
      status,
      headers: {
        "Content-Type":
          status < 400 ? "application/json" : "application/problem+json",
      },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

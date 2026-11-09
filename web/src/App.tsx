import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router";
import { routes } from "./routes";

const queryClient = new QueryClient({
  defaultOptions: {
    // The API caches for 5 minutes and data changes every 3 hours, so don't refetch eagerly
    queries: { staleTime: 5 * 60_000, refetchOnWindowFocus: false },
  },
});

const router = createBrowserRouter(routes);

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}

export default App;

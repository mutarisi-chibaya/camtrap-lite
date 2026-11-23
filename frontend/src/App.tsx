import { useQuery } from "@tanstack/react-query";
import { getHealth } from "./api/client";

export default function App() {
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth });

  return (
    <main className="app">
      <h1>CamTrap Lite</h1>
      <p>
        API status:{" "}
        {health.isPending ? "checking…" : health.isError ? "unreachable" : health.data.status}
      </p>
    </main>
  );
}

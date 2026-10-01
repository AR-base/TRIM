import { useEffect, useState } from "react";

export type Route =
  | { name: "overview" }
  | { name: "agents" }
  | { name: "agent"; id: number }
  | { name: "alerts" }
  | { name: "requests" }
  | { name: "history" };

export function parseHash(hash: string): Route {
  const path = hash.replace(/^#/, "").replace(/\/+$/, "") || "/";
  const agent = /^\/agents\/(\d{1,9})$/.exec(path);
  if (agent?.[1]) return { name: "agent", id: Number(agent[1]) };
  switch (path) {
    case "/agents":
      return { name: "agents" };
    case "/alerts":
      return { name: "alerts" };
    case "/requests":
      return { name: "requests" };
    case "/history":
      return { name: "history" };
    default:
      return { name: "overview" };
  }
}

export function href(route: Route): string {
  switch (route.name) {
    case "overview":
      return "#/";
    case "agent":
      return `#/agents/${route.id}`;
    default:
      return `#/${route.name}`;
  }
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => {
      setRoute(parseHash(window.location.hash));
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

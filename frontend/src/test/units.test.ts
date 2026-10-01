import { describe, expect, it, vi } from "vitest";

import { ApiError, createClient } from "../api";
import { plural, relativeTime, riskLabel, shortDate } from "../format";
import { href, parseHash } from "../router";

describe("format", () => {
  it("pluralises", () => {
    expect(plural(1, "agent")).toBe("1 agent");
    expect(plural(2, "person", "people")).toBe("2 people");
    expect(plural(1200, "call")).toBe("1,200 calls");
  });

  it("describes relative time", () => {
    const now = new Date("2026-09-29T12:00:00Z");
    expect(relativeTime(null, now)).toBe("never");
    expect(relativeTime("2026-09-29T11:59:40Z", now)).toBe("just now");
    expect(relativeTime("2026-09-29T11:00:00Z", now)).toBe("1 hour ago");
    expect(relativeTime("2026-09-26T12:00:00Z", now)).toBe("3 days ago");
    expect(relativeTime("2026-09-29T12:30:00Z", now)).toBe("in 30 minutes");
    expect(relativeTime("not a date", now)).toBe("unknown");
  });

  it("formats dates in UTC and clamps risk", () => {
    expect(shortDate("2026-09-07")).toBe("7 Sept");
    expect(riskLabel(3)).toBe("High");
    expect(riskLabel(9)).toBe("High");
    expect(riskLabel(-1)).toBe("None");
  });
});

describe("router", () => {
  it("parses known routes and falls back to overview", () => {
    expect(parseHash("#/agents/42")).toEqual({ name: "agent", id: 42 });
    expect(parseHash("#/alerts/")).toEqual({ name: "alerts" });
    expect(parseHash("#/agents/../../etc")).toEqual({ name: "overview" });
    expect(parseHash("")).toEqual({ name: "overview" });
    expect(parseHash("#/agents/1e9")).toEqual({ name: "overview" });
  });

  it("builds hrefs", () => {
    expect(href({ name: "agent", id: 7 })).toBe("#/agents/7");
    expect(href({ name: "overview" })).toBe("#/");
    expect(href({ name: "history" })).toBe("#/history");
  });
});

describe("api client", () => {
  it("sends the bearer token and JSON body", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1 }), { status: 200 }));
    const client = createClient(fetcher, () => "trim_abc");
    await client.trim(5, true);
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe("/api/v1/agents/5/trim");
    expect(init.method).toBe("POST");
    expect(init.headers.Authorization).toBe("Bearer trim_abc");
    expect(init.credentials).toBe("omit");
    expect(JSON.parse(init.body)).toEqual({ confirm_revoke: true });
  });

  it("encodes query parameters and skips empty ones", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
    const client = createClient(fetcher, () => null);
    await client.agents({ state: "", q: "mail & co", can: "send_email" });
    expect(fetcher.mock.calls[0]![0]).toBe("/api/v1/agents?q=mail+%26+co&can=send_email");
    expect(fetcher.mock.calls[0]![1].headers.Authorization).toBeUndefined();
  });

  it("turns API errors into ApiError with the server's code", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "needs_confirmation", detail: "Confirm to continue." }), { status: 409 }),
    );
    const err = await createClient(fetcher, () => "t").trim(1).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("needs_confirmation");
    expect(err.status).toBe(409);
    expect(err.message).toBe("Confirm to continue.");
  });

  it("reports network failures and non-JSON errors", async () => {
    const down = createClient(vi.fn().mockRejectedValue(new TypeError("fail")), () => "t");
    await expect(down.summary()).rejects.toMatchObject({ code: "network", status: 0 });
    const html = createClient(vi.fn().mockResolvedValue(new Response("<h1>Bad gateway</h1>", { status: 502, statusText: "Bad Gateway" })), () => "t");
    await expect(html.summary()).rejects.toMatchObject({ code: "http_502", status: 502 });
  });
});

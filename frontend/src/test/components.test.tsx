import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ActivityBars } from "../components/ActivityBars";
import { StateBadge } from "../components/Bits";
import { CountStrip, PermissionStrip } from "../components/Strip";
import { SignIn } from "../pages/SignIn";
import type { ScopeView } from "../types";

const scope = (short: string, status: ScopeView["status"], risk = 2): ScopeView => ({
  scope: `https://www.googleapis.com/auth/${short}`,
  short,
  phrase: `do ${short}`,
  risk,
  status,
  narrowed_to: [],
  users: 1,
  essential: short === "openid",
});

describe("PermissionStrip", () => {
  it("draws one segment per meaningful permission, sized by risk", () => {
    const { container } = render(
      <PermissionStrip scopes={[scope("openid", "used", 0), scope("mail.full", "narrowed", 3), scope("calendar", "unused", 1)]} />,
    );
    const segs = container.querySelectorAll(".strip__seg");
    expect(segs).toHaveLength(2); // identity scopes are not drawn
    expect(segs[0]!.getAttribute("data-status")).toBe("narrowed");
    expect((segs[0] as HTMLElement).style.flexGrow).toBe("3");
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("mail.full: can be narrowed, calendar: unused");
  });

  it("handles agents with nothing to show", () => {
    render(<PermissionStrip scopes={[]} />);
    expect(screen.getByLabelText("No permissions")).toBeTruthy();
  });

  it("summarises counts in compact form", () => {
    render(<CountStrip granted={5} unused={3} />);
    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("2 in use, 3 unused");
  });
});

describe("ActivityBars", () => {
  it("marks alert days and excluded days", () => {
    const days = [
      { day: "2026-09-01", calls: 10 },
      { day: "2026-09-02", calls: 0 },
      { day: "2026-09-03", calls: 40 },
    ];
    const { container } = render(<ActivityBars days={days} flagged={["2026-09-03"]} excluded={["2026-09-02"]} />);
    expect(container.querySelector(".bars__bar--alert")?.getAttribute("title")).toContain("40 calls");
    expect(container.querySelectorAll(".bars__bar--excluded")).toHaveLength(1);
    expect(screen.getByLabelText("50 API calls over 3 days")).toBeTruthy();
  });
});

describe("StateBadge", () => {
  it("labels states in plain words", () => {
    render(<StateBadge state="ready" />);
    expect(screen.getByText("Can be trimmed").getAttribute("title")).toBe("Holds permissions it never used");
  });
});

describe("SignIn", () => {
  it("asks for a token before calling the API", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<SignIn onSignedIn={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(screen.getByText("Paste the access token your administrator gave you.")).toBeTruthy();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("rejects an invalid token and clears it", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: "http_401", detail: "missing or invalid token" }), { status: 401 }),
    );
    const onSignedIn = vi.fn();
    render(<SignIn onSignedIn={onSignedIn} />);
    await userEvent.type(screen.getByLabelText("Access token"), "trim_wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("That token isn't valid.")).toBeTruthy();
    expect(onSignedIn).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("trim.token")).toBeNull();
    fetchSpy.mockRestore();
  });

  it("refuses machine tokens", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ name: "bot", role: "service", can_change_access: false }), { status: 200 }),
    );
    const onSignedIn = vi.fn();
    render(<SignIn onSignedIn={onSignedIn} />);
    await userEvent.type(screen.getByLabelText("Access token"), "trim_bot");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText(/machine token/)).toBeTruthy();
    expect(onSignedIn).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("signs in an admin", async () => {
    const me = { name: "ana", role: "admin", can_change_access: true };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(me), { status: 200 }));
    const onSignedIn = vi.fn();
    render(<SignIn onSignedIn={onSignedIn} />);
    await userEvent.type(screen.getByLabelText("Access token"), "  trim_good  ");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await vi.waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(me));
    expect(sessionStorage.getItem("trim.token")).toBe("trim_good");
    fetchSpy.mockRestore();
  });
});

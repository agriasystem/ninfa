// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DatiScreenProps } from "@/components/dati-screen";

const push = vi.fn();
const replace = vi.fn();
let search = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(search),
}));

// The screen itself is covered by `dati-screen.test.tsx`: here only the URL wiring matters, so it is a
// stub that shows what the page hands it and lets a test trigger every callback.
vi.mock("@/components/dati-screen", () => ({
  DatiScreen: (props: DatiScreenProps) => (
    <div>
      <p data-testid="props">{JSON.stringify({ property: props.requestedPropertyId, tab: props.tab, period: props.period })}</p>
      <button onClick={() => props.onSelectTab("costs")}>tab-costs</button>
      <button onClick={() => props.onSelectPeriod(7)}>period-7</button>
      <button onClick={() => props.onSelectPeriod(30)}>period-30</button>
      <button onClick={() => props.onSelectProperty("p2")}>property-p2</button>
      <button onClick={props.onNavigateToLogin}>login</button>
    </div>
  ),
}));

import DatiPage from "./page";

const passed = () => JSON.parse(screen.getByTestId("props").textContent ?? "{}") as { property: string | null; tab: string; period: number };

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  search = "";
});

describe("/dati page - the URL is the state", () => {
  it("reads the property, the tab and the period from the query", () => {
    search = "property=p1&tab=bookings&period=7";
    render(<DatiPage />);

    expect(passed()).toEqual({ property: "p1", tab: "bookings", period: 7 });
  });

  it("defaults to Panoramica and 30 days, and ignores a bad tab or period", () => {
    search = "property=p1&tab=hack&period=14";
    render(<DatiPage />);

    expect(passed()).toEqual({ property: "p1", tab: "overview", period: 30 });
  });

  it("pushes a history entry for a tab the user chooses (so back / forward walk through the tabs)", async () => {
    search = "property=p1&tab=overview&period=7";
    render(<DatiPage />);

    await userEvent.click(screen.getByText("tab-costs"));

    expect(push).toHaveBeenCalledWith("/dati?property=p1&tab=costs&period=7");
    expect(replace).not.toHaveBeenCalled();
  });

  it("pushes a history entry for a period, keeping the tab; 30 days is the unwritten default", async () => {
    search = "property=p1&tab=bookings";
    render(<DatiPage />);

    await userEvent.click(screen.getByText("period-7"));
    expect(push).toHaveBeenLastCalledWith("/dati?property=p1&tab=bookings&period=7");
    await userEvent.click(screen.getByText("period-30"));
    expect(push).toHaveBeenLastCalledWith("/dati?property=p1&tab=bookings");
  });

  it("REPLACES (never pushes) when the property is resolved or switched, keeping tab and period", async () => {
    search = "property=p1&tab=costs&period=7";
    render(<DatiPage />);

    await userEvent.click(screen.getByText("property-p2"));

    expect(replace).toHaveBeenCalledWith("/dati?property=p2&tab=costs&period=7");
    expect(push).not.toHaveBeenCalled();
  });

  it("does nothing on a tab or period choice while no property is resolved yet", async () => {
    search = "";
    render(<DatiPage />);

    await userEvent.click(screen.getByText("tab-costs"));
    await userEvent.click(screen.getByText("period-7"));

    expect(push).not.toHaveBeenCalled();
  });

  it("sends an unauthenticated visitor to the login page", async () => {
    render(<DatiPage />);

    await userEvent.click(screen.getByText("login"));

    expect(replace).toHaveBeenCalledWith("/login");
  });
});

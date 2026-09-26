// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PropertyAccess } from "@ninfa/contracts";

import { PropertySelector } from "./property-selector";

function property(id: string, name: string): PropertyAccess {
  return { id, name, slug: name.toLowerCase(), timezone: "Europe/Rome" };
}

describe("PropertySelector", () => {
  it("renders nothing when there is a single property (auto-selected elsewhere)", () => {
    const { container } = render(
      <PropertySelector
        properties={[property("p1", "Masseria Ninfa")]}
        selectedPropertyId="p1"
        onSelect={vi.fn()}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when there are zero properties", () => {
    const { container } = render(
      <PropertySelector properties={[]} selectedPropertyId="" onSelect={vi.fn()} />,
    );

    expect(container.firstChild).toBeNull();
  });

  it("shows every accessible property as an option when there is more than one", () => {
    render(
      <PropertySelector
        properties={[property("p1", "Masseria Ninfa"), property("p2", "Villa Astra")]}
        selectedPropertyId="p1"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("option", { name: "Masseria Ninfa" })).not.toBeNull();
    expect(screen.getByRole("option", { name: "Villa Astra" })).not.toBeNull();
  });

  it("is a real <select> keyboard-operable control with an accessible label", () => {
    render(
      <PropertySelector
        properties={[property("p1", "Masseria Ninfa"), property("p2", "Villa Astra")]}
        selectedPropertyId="p1"
        onSelect={vi.fn()}
      />,
    );

    const select = screen.getByLabelText("Struttura") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
  });

  it("calls onSelect with the chosen property's id when switched", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <PropertySelector
        properties={[property("p1", "Masseria Ninfa"), property("p2", "Villa Astra")]}
        selectedPropertyId="p1"
        onSelect={onSelect}
      />,
    );

    await user.selectOptions(screen.getByLabelText("Struttura"), "p2");

    expect(onSelect).toHaveBeenCalledWith("p2");
  });
});

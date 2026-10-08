import { describe, expect, it } from "vitest";

import { copy } from "@/lib/copy";

import { firstNameOf } from "./greeting";

describe("firstNameOf", () => {
  it("takes the first whitespace-separated token of the display name", () => {
    expect(firstNameOf("Giulia Rossi")).toBe("Giulia");
    expect(firstNameOf("Anna Maria Verdi")).toBe("Anna");
  });

  it("trims surrounding whitespace and collapses any run of whitespace", () => {
    expect(firstNameOf("   Marco   Neri  ")).toBe("Marco");
    expect(firstNameOf("\tElena\nBianchi")).toBe("Elena");
  });

  it("returns a single-word name as is", () => {
    expect(firstNameOf("Chiara")).toBe("Chiara");
  });

  it("keeps accents and apostrophes intact", () => {
    expect(firstNameOf("Niccolò De' Medici")).toBe("Niccolò");
    expect(firstNameOf("D'Angelo Luca")).toBe("D'Angelo");
  });

  it("returns null for null, undefined, empty and whitespace-only names", () => {
    expect(firstNameOf(null)).toBeNull();
    expect(firstNameOf(undefined)).toBeNull();
    expect(firstNameOf("")).toBeNull();
    expect(firstNameOf("    ")).toBeNull();
  });
});

describe("greeting copy", () => {
  it("reads 'Ciao {nome},' for a name and a bare 'Ciao,' without one", () => {
    expect(copy.home.greeting("Giulia")).toBe("Ciao Giulia,");
    expect(copy.home.greeting(null)).toBe("Ciao,");
  });

  it("is never derived from an e-mail address", () => {
    // The API only ever gives `display_name`; nothing in this module reads an e-mail.
    expect(copy.home.greeting(firstNameOf(null))).toBe("Ciao,");
  });
});

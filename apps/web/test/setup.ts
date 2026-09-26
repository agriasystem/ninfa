import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Every component test renders into jsdom's shared document; without this, one test's tree
// stays mounted for the next one, and `screen.getByX` starts matching duplicates across tests.
afterEach(() => {
  cleanup();
});

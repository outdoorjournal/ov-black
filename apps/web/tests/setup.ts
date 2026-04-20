import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// RTL auto-cleans when `globals: true`; we keep globals off, so wire it up
// manually. Without this, successive render() calls stack <main> roots into
// document.body and ambiguous queries (e.g. getByTestId) explode.
afterEach(() => {
  cleanup();
});

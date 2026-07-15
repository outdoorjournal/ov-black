import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// RTL auto-cleans when `globals: true`; we keep globals off, so wire it up
// manually. Without this, successive render() calls stack <main> roots into
// document.body and ambiguous queries (e.g. getByTestId) explode.
afterEach(() => {
  cleanup();
});

// jsdom ships no ResizeObserver; components that measure themselves (e.g. the
// Journal's journey-thread sizing) need a no-op stand-in. Layout observations
// simply never fire in tests — assertions must not depend on measured sizes.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

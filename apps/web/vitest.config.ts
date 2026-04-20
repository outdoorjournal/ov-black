import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  // Use esbuild's automatic JSX runtime so test files don't need to import
  // React explicitly (matching Next 15 + React 19 behaviour in app code).
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
});

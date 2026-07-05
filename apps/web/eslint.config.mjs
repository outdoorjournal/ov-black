// Flat config for ESLint 9 / Next 16 (which removed `next lint`). eslint-config-next
// v16 ships a native flat-config array, so we spread it directly — no FlatCompat
// shim. `next/core-web-vitals` bundles the base `next`, `next/typescript`, and the
// core-web-vitals rules, matching (and slightly extending) the rule surface the
// project had under `.eslintrc.json`. `next lint` used to auto-ignore build output;
// under the ESLint CLI we declare those ignores ourselves.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "next-env.d.ts",
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
    ],
  },
  ...nextCoreWebVitals,
  {
    // React Compiler lint rules — DELIBERATELY OFF (not debt).
    //
    // eslint-config-next 16 bundles eslint-plugin-react-hooks v6+, which ships
    // the React Compiler rule set. This project does NOT use the React Compiler,
    // and these rules flag patterns the codebase uses idiomatically and on
    // purpose — every current finding was reviewed and is intentional, not a bug:
    //   • refs / immutability / preserve-manual-memoization — reading a ref
    //     during render for scroll-anchoring (ConversationStream), a StrictMode-
    //     safe phase counter (lib/atmos/classifier usePhaseShiftMood), and the
    //     freshly-arrived-proposal auto-scroll (HorizontalView). All documented
    //     at their sites.
    //   • set-state-in-effect — setState in an effect to react to an external
    //     store signal (e.g. CollectionOverlay auto-closing when a card is held).
    //   • incompatible-library — react-hook-form's `form.watch()`, which is not
    //     compiler-optimizable by nature (not fixable without changing libraries).
    //
    // Turning these on would mean rewriting correct code (behavior-risky) or
    // carrying disables at every idiomatic use forever. Revisit only as part of a
    // deliberate React Compiler adoption, not as a lint cleanup.
    rules: {
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/immutability": "off",
      "react-hooks/preserve-manual-memoization": "off",
      "react-hooks/incompatible-library": "off",
    },
  },
];

export default eslintConfig;

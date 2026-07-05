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
    // eslint-config-next 16 bundles eslint-plugin-react-hooks v6+ (the React
    // Compiler rule set). None of these rules existed under the project's prior
    // v15 `next/core-web-vitals`; enabling them as hard errors would turn this
    // framework upgrade into an unrelated ~37-site refactor. Preserve the prior
    // lint surface here and address the React Compiler findings as a separate,
    // deliberate follow-up (tracked in the upgrade PR description).
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

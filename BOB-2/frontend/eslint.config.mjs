import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // The backend returns several heterogeneous accounting/ERP payloads whose
      // shapes are narrowed at render or gateway boundaries. Keep strict
      // TypeScript build checks enabled, but avoid noisy lint-only warnings for
      // intentionally flexible API payloads.
      "@typescript-eslint/no-explicit-any": "off",

      // Client-side hydration and data-fetching effects intentionally update
      // state after mount throughout this application. React's exhaustive-deps
      // rule remains enabled; this newer compiler advisory is too noisy for the
      // current Next.js client pages and does not indicate a failed build.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;

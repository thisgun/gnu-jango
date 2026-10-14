import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// eslint-config-next 16 exports flat configs directly (the FlatCompat bridge no longer loads it).
const eslintConfig = [
  {
    ignores: [
      ".next/**",
      ".next-*/**",
      ".deploy/**",
      "out/**",
      "node_modules/**",
      "test-results/**",
      "next-start-*.log",
      "*.tsbuildinfo",
      "next-env.d.ts",
    ],
  },
  ...nextVitals,
  ...nextTypescript,
  {
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      "react-hooks/exhaustive-deps": "warn",
      // React Compiler rules added by eslint-plugin-react-hooks 6/7 (Next 16). The codebase is not
      // written for the compiler, so they are off, as in the reference project.
      "react-hooks/immutability": "off",
      "react-hooks/preserve-manual-memoization": "off",
      "react-hooks/set-state-in-effect": "off",
      "prefer-const": "warn",
      "@next/next/no-img-element": "off",
      "@next/next/no-html-link-for-pages": "off",
    },
  },
  {
    files: ["scripts/**/*.mjs"],
    rules: {
      "@next/next/no-assign-module-variable": "off",
    },
  },
];

export default eslintConfig;

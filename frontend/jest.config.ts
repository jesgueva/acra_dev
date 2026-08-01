import type { Config } from "jest";

const config: Config = {
  testEnvironment: "jest-environment-jsdom",
  transform: {
    "^.+\\.(ts|tsx)$": [
      "ts-jest",
      {
        tsconfig: {
          jsx: "react-jsx",
        },
      },
    ],
  },
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
    "^next-intl$": "<rootDir>/src/__mocks__/next-intl.tsx",
    "^next/navigation$": "<rootDir>/src/__mocks__/next-navigation.ts",
    "^next/headers$": "<rootDir>/src/__mocks__/next-headers.ts",
  },
  setupFilesAfterEnv: ["<rootDir>/jest.setup.ts"],
  // Playwright specs live in e2e/ and are driven by playwright.config.ts —
  // Jest's default testMatch would otherwise pick up their .spec.ts files.
  testPathIgnorePatterns: ["<rootDir>/node_modules/", "<rootDir>/e2e/"],
  // Scoped to the tested layers (components, lib, contexts) — not `app/` routing shells or the
  // vendored shadcn primitives at the repo-root `components/ui/` (outside `src/`, see CLAUDE.md's
  // import-path convention). `src/components/ui/` itself IS app-authored (CreatableCombobox) and
  // stays in scope.
  collectCoverageFrom: [
    "src/components/**/*.{ts,tsx}",
    "src/lib/**/*.{ts,tsx}",
    "src/contexts/**/*.{ts,tsx}",
    "!src/**/__tests__/**",
    "!src/**/__mocks__/**",
  ],
  // Measured on `npx jest --coverage` at ticket-46 (A10-3): statements 64.14%, branches 58.44%,
  // functions 49.25%, lines 65.88%. Floor is that real number rounded down to the nearest 5, not
  // an aspirational target. Raise it deliberately as coverage improves; do not lower it to make a
  // failing PR pass.
  coverageThreshold: {
    global: {
      statements: 60,
      branches: 55,
      functions: 45,
      lines: 65,
    },
  },
};

export default config;

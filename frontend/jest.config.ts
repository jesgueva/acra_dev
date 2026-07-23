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
};

export default config;

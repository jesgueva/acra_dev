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
};

export default config;

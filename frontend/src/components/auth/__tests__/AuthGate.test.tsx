import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import AuthGate from "../AuthGate";
import { AuthContextValue } from "@/src/contexts/AuthContext";

jest.mock("next/navigation", () => ({
  useRouter: jest.fn(),
  usePathname: jest.fn(),
}));

jest.mock("next-intl", () => ({
  useLocale: () => "en",
}));

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "@/src/contexts/AuthContext";

const mockReplace = jest.fn();

function makeAuth(overrides: Partial<AuthContextValue> = {}): AuthContextValue {
  return {
    user: {
      user_id: 1,
      full_name: "Test User",
      roles: ["Admin"],
      preferred_language: "en",
      effective_privileges: [],
    },
    token: "tok",
    isAuthenticated: true,
    authResolved: true,
    login: jest.fn(),
    logout: jest.fn(),
    hasPrivilege: jest.fn(() => false),
    ...overrides,
  };
}

beforeEach(() => {
  (useRouter as jest.Mock).mockReturnValue({
    replace: mockReplace,
    push: jest.fn(),
    refresh: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    prefetch: jest.fn(),
  });
  (usePathname as jest.Mock).mockReturnValue("/en/inventory");
  (useAuth as jest.Mock).mockReturnValue(makeAuth());
  mockReplace.mockClear();
});

test("renders protected children when auth is resolved", () => {
  render(
    <AuthGate>
      <div>Protected Page</div>
    </AuthGate>
  );

  expect(screen.getByText("Protected Page")).toBeInTheDocument();
});

test("redirects unauthenticated users from protected pages", async () => {
  (useAuth as jest.Mock).mockReturnValue(
    makeAuth({
      user: null,
      token: null,
      isAuthenticated: false,
      authResolved: true,
    })
  );

  const { container } = render(
    <AuthGate>
      <div>Protected Page</div>
    </AuthGate>
  );

  expect(container).toBeEmptyDOMElement();

  await waitFor(() => {
    expect(mockReplace).toHaveBeenCalledWith("/en/login");
  });
});

test("allows the login page to render without a session", () => {
  (usePathname as jest.Mock).mockReturnValue("/en/login");
  (useAuth as jest.Mock).mockReturnValue(
    makeAuth({
      user: null,
      token: null,
      isAuthenticated: false,
      authResolved: true,
    })
  );

  render(
    <AuthGate>
      <div>Login Page</div>
    </AuthGate>
  );

  expect(screen.getByText("Login Page")).toBeInTheDocument();
  expect(mockReplace).not.toHaveBeenCalled();
});

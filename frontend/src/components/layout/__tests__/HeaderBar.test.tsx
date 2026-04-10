import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HeaderBar from "../HeaderBar";
import { AuthContextValue } from "@/src/contexts/AuthContext";

jest.mock("next/navigation", () => ({
  useRouter: jest.fn(),
  usePathname: jest.fn(),
}));

jest.mock("next-intl", () => ({
  useTranslations: () => (key: string) => `nav.${key}`,
  useLocale: () => "en",
}));

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@/src/components/brand/AcraLogo", () => {
  function AcraLogoMock() {
    return <div data-testid="acra-logo">ACRA Logo</div>;
  }
  return AcraLogoMock;
});

import { useRouter, usePathname } from "next/navigation";
import { useAuth } from "@/src/contexts/AuthContext";

const mockReplace = jest.fn();

function makeAuth(
  overrides: Partial<AuthContextValue> = {}
): AuthContextValue {
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
    logout: jest.fn().mockResolvedValue(undefined),
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

test("renders user name and logout action for authenticated pages", () => {
  render(<HeaderBar />);

  expect(screen.getByTestId("acra-logo")).toBeInTheDocument();
  expect(screen.getByText("Test User")).toBeInTheDocument();
  expect(screen.getByLabelText("logout")).toBeInTheDocument();
  expect(screen.getByText("nav.logout")).toBeInTheDocument();
});

test("hides the header on the login page", () => {
  (usePathname as jest.Mock).mockReturnValue("/en/login");

  const { container } = render(<HeaderBar />);

  expect(container).toBeEmptyDOMElement();
});

test("logs out and redirects to localized login", async () => {
  const mockLogout = jest.fn().mockResolvedValue(undefined);
  (useAuth as jest.Mock).mockReturnValue(makeAuth({ logout: mockLogout }));

  render(<HeaderBar />);

  await userEvent.click(screen.getByLabelText("logout"));

  await waitFor(() => {
    expect(mockLogout).toHaveBeenCalled();
    expect(mockReplace).toHaveBeenCalledWith("/en/login");
  });
});

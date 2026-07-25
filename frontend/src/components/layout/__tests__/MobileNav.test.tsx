import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MobileNav from "../MobileNav";
import { NAV_ITEMS } from "../navItems";
import { AuthContextValue } from "@/src/contexts/AuthContext";
import { PRIVILEGES } from "@/src/lib/privileges";

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@/src/components/layout/ThemeToggle", () => ({
  ThemeToggle: () => <button>theme</button>,
}));

import { useAuth } from "@/src/contexts/AuthContext";

const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

function makeAuth(privileges: string[]): AuthContextValue {
  return {
    user: {
      user_id: 1,
      full_name: "Test User",
      roles: ["receiving_clerk"],
      preferred_language: "en",
      effective_privileges: privileges,
    },
    token: "test-token",
    isAuthenticated: true,
    authResolved: true,
    login: jest.fn(),
    logout: jest.fn(),
    hasPrivilege: (p: string) => privileges.includes(p),
  };
}

beforeEach(() => jest.clearAllMocks());

test("renders nothing when signed out", () => {
  mockUseAuth.mockReturnValue({ ...makeAuth([]), isAuthenticated: false });

  const { container } = render(<MobileNav />);

  expect(container).toBeEmptyDOMElement();
});

test("the drawer lists only the modules the viewer may open", async () => {
  const user = userEvent.setup();
  mockUseAuth.mockReturnValue(
    makeAuth([PRIVILEGES.RECEIVING_VIEW, PRIVILEGES.INVENTORY_VIEW]),
  );

  render(<MobileNav />);
  await user.click(screen.getByTestId("mobile-nav-trigger"));

  expect(screen.getByRole("link", { name: /receiving/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /inventory/i })).toBeInTheDocument();

  // The drawer must not become a second, unguarded way into the admin modules.
  expect(screen.queryByRole("link", { name: /^users$/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /audit/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /work orders/i })).not.toBeInTheDocument();
});

test("an admin sees every module", async () => {
  const user = userEvent.setup();
  mockUseAuth.mockReturnValue(makeAuth(NAV_ITEMS.map((item) => item.privilege)));

  render(<MobileNav />);
  await user.click(screen.getByTestId("mobile-nav-trigger"));

  for (const item of NAV_ITEMS) {
    expect(screen.getByRole("link", { name: new RegExp(item.key, "i") })).toBeInTheDocument();
  }
});

test("links carry the locale prefix", async () => {
  const user = userEvent.setup();
  mockUseAuth.mockReturnValue(makeAuth([PRIVILEGES.INVENTORY_VIEW]));

  render(<MobileNav />);
  await user.click(screen.getByTestId("mobile-nav-trigger"));

  // A bare /inventory would miss the locale segment and bounce through a redirect.
  expect(screen.getByRole("link", { name: /inventory/i })).toHaveAttribute(
    "href",
    "/en/inventory",
  );
});

import React from "react";
import { render, screen } from "@testing-library/react";
import NavSidebar from "../NavSidebar";
import { AuthContextValue } from "@/src/contexts/AuthContext";
import { PRIVILEGES } from "@/src/lib/privileges";

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@/src/lib/api-client", () => ({
  apiClient: { patch: jest.fn() },
}));

import { useAuth } from "@/src/contexts/AuthContext";

const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

function makeAuth(privileges: string[]): AuthContextValue {
  return {
    user: {
      user_id: 1,
      full_name: "Test User",
      roles: ["operator"],
      preferred_language: "en",
      effective_privileges: privileges,
    },
    token: "tok",
    isAuthenticated: true,
    authResolved: true,
    login: jest.fn(),
    logout: jest.fn(),
    hasPrivilege: (p: string) => privileges.includes(p),
  };
}

test("shows nav links only for privileges the user has", () => {
  mockUseAuth.mockReturnValue(
    makeAuth([PRIVILEGES.RECEIVING_VIEW, PRIVILEGES.INVENTORY_VIEW])
  );

  render(<NavSidebar />);

  expect(screen.getByText("nav.receiving")).toBeInTheDocument();
  expect(screen.getByText("nav.inventory")).toBeInTheDocument();
  expect(screen.queryByText("nav.workOrders")).not.toBeInTheDocument();
  expect(screen.queryByText("nav.users")).not.toBeInTheDocument();
  expect(screen.queryByText("nav.audit")).not.toBeInTheDocument();
});

test("hides all nav links when user has no privileges", () => {
  mockUseAuth.mockReturnValue(makeAuth([]));

  render(<NavSidebar />);

  expect(screen.queryByText("nav.receiving")).not.toBeInTheDocument();
  expect(screen.queryByText("nav.inventory")).not.toBeInTheDocument();
  expect(screen.queryByText("nav.workOrders")).not.toBeInTheDocument();
  expect(screen.queryByText("nav.shippingNav")).not.toBeInTheDocument();
  expect(screen.queryByText("nav.users")).not.toBeInTheDocument();
  expect(screen.queryByText("nav.audit")).not.toBeInTheDocument();
  expect(screen.getByText("nav.logout")).toBeInTheDocument();
});

test("shows the Shipping link to a user holding shipping.view", () => {
  mockUseAuth.mockReturnValue(makeAuth([PRIVILEGES.SHIPPING_VIEW]));

  render(<NavSidebar />);

  expect(screen.getByText("nav.shippingNav").closest("a")).toHaveAttribute(
    "href",
    "/en/shipping"
  );
});

test("hides the Shipping link from a user without shipping.view", () => {
  // ACR-35: the entry shipped commented out with a RECEIVING_VIEW placeholder privilege.
  // Holding every *other* nav privilege must still not surface Shipping.
  mockUseAuth.mockReturnValue(
    makeAuth([
      PRIVILEGES.RECEIVING_VIEW,
      PRIVILEGES.INVENTORY_VIEW,
      PRIVILEGES.USERS_MANAGE,
      PRIVILEGES.AUDIT_VIEW,
      PRIVILEGES.SHIPPING_CREATE,
    ])
  );

  render(<NavSidebar />);

  expect(screen.queryByText("nav.shippingNav")).not.toBeInTheDocument();
});

test("shows the Users and Audit links to an admin holding both privileges", () => {
  mockUseAuth.mockReturnValue(
    makeAuth([
      PRIVILEGES.RECEIVING_VIEW,
      PRIVILEGES.INVENTORY_VIEW,
      PRIVILEGES.USERS_MANAGE,
      PRIVILEGES.AUDIT_VIEW,
    ])
  );

  render(<NavSidebar />);

  expect(screen.getByText("nav.users").closest("a")).toHaveAttribute(
    "href",
    "/en/users"
  );
  expect(screen.getByText("nav.audit").closest("a")).toHaveAttribute(
    "href",
    "/en/audit"
  );
});

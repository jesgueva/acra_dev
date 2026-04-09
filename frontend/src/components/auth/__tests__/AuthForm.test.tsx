import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AuthForm from "../AuthForm";
import { AuthContextValue } from "@/src/contexts/AuthContext";

// Mock next/navigation — must come before import of the component
jest.mock("next/navigation", () => ({
  useRouter: jest.fn(),
  useSearchParams: jest.fn(),
  usePathname: jest.fn(() => "/"),
  redirect: jest.fn(),
}));

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/src/contexts/AuthContext";

const mockPush = jest.fn();

function makeAuth(
  loginImpl: () => Promise<void> = jest.fn().mockResolvedValue(undefined)
): AuthContextValue {
  return {
    user: null,
    token: null,
    isAuthenticated: false,
    login: loginImpl,
    logout: jest.fn(),
    hasPrivilege: jest.fn(() => false),
  };
}

beforeEach(() => {
  (useRouter as jest.Mock).mockReturnValue({
    push: mockPush,
    replace: jest.fn(),
    refresh: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
    prefetch: jest.fn(),
  });
  (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams());
  (useAuth as jest.Mock).mockReturnValue(makeAuth());
  mockPush.mockClear();
});

test("renders username and password inputs and submit button", () => {
  render(<AuthForm />);

  expect(screen.getByLabelText("auth.username")).toBeInTheDocument();
  expect(screen.getByLabelText("auth.password")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "auth.loginButton" })
  ).toBeInTheDocument();
});

test("shows sessionExpired message when reason=session_expired param present", () => {
  (useSearchParams as jest.Mock).mockReturnValue(
    new URLSearchParams("reason=session_expired")
  );

  render(<AuthForm />);

  expect(screen.getByText("auth.sessionExpired")).toBeInTheDocument();
});

test("calls login with typed credentials on submit", async () => {
  const mockLogin = jest.fn().mockResolvedValue(undefined);
  (useAuth as jest.Mock).mockReturnValue(makeAuth(mockLogin));

  render(<AuthForm />);

  await userEvent.type(screen.getByLabelText("auth.username"), "admin");
  await userEvent.type(screen.getByLabelText("auth.password"), "secret123");
  await userEvent.click(screen.getByRole("button", { name: "auth.loginButton" }));

  expect(mockLogin).toHaveBeenCalledWith({
    username: "admin",
    password: "secret123",
  });
});

test("disables submit button while login is in progress", async () => {
  // Never-resolving promise keeps loading state indefinitely
  const mockLogin = jest.fn().mockReturnValue(new Promise(() => {}));
  (useAuth as jest.Mock).mockReturnValue(makeAuth(mockLogin));

  render(<AuthForm />);

  await userEvent.type(screen.getByLabelText("auth.username"), "admin");
  await userEvent.type(screen.getByLabelText("auth.password"), "pass");
  await userEvent.click(screen.getByRole("button", { name: "auth.loginButton" }));

  await waitFor(() => {
    expect(screen.getByRole("button")).toBeDisabled();
  });
});

test("redirects to /dashboard after successful login", async () => {
  const mockLogin = jest.fn().mockResolvedValue(undefined);
  (useAuth as jest.Mock).mockReturnValue(makeAuth(mockLogin));

  render(<AuthForm />);

  await userEvent.type(screen.getByLabelText("auth.username"), "admin");
  await userEvent.type(screen.getByLabelText("auth.password"), "pass");
  await userEvent.click(screen.getByRole("button", { name: "auth.loginButton" }));

  await waitFor(() => {
    expect(mockPush).toHaveBeenCalledWith("/dashboard");
  });
});

test("shows invalidCredentials error when login throws 401", async () => {
  const err = Object.assign(new Error("Unauthorized"), { status: 401 });
  const mockLogin = jest.fn().mockRejectedValue(err);
  (useAuth as jest.Mock).mockReturnValue(makeAuth(mockLogin));

  render(<AuthForm />);

  await userEvent.type(screen.getByLabelText("auth.username"), "admin");
  await userEvent.type(screen.getByLabelText("auth.password"), "wrong");
  await userEvent.click(screen.getByRole("button", { name: "auth.loginButton" }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(
      "auth.invalidCredentials"
    );
  });
});

test("shows accountDeactivated error when login throws 403", async () => {
  const err = Object.assign(new Error("Forbidden"), { status: 403 });
  const mockLogin = jest.fn().mockRejectedValue(err);
  (useAuth as jest.Mock).mockReturnValue(makeAuth(mockLogin));

  render(<AuthForm />);

  await userEvent.type(screen.getByLabelText("auth.username"), "admin");
  await userEvent.type(screen.getByLabelText("auth.password"), "pass");
  await userEvent.click(screen.getByRole("button", { name: "auth.loginButton" }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent(
      "auth.accountDeactivated"
    );
  });
});

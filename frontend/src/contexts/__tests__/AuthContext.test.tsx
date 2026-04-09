import React from "react";
import { render, screen, act, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "../AuthContext";

// Silence fetch-related noise in tests
beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    json: async () => ({}),
  });
});

afterEach(() => {
  jest.resetAllMocks();
});

function TestConsumer() {
  const { isAuthenticated, user, hasPrivilege } = useAuth();
  return (
    <div>
      <span data-testid="is-auth">{String(isAuthenticated)}</span>
      <span data-testid="user">{user?.full_name ?? "none"}</span>
      <span data-testid="priv-receiving">{String(hasPrivilege("receiving.view"))}</span>
    </div>
  );
}

test("provides isAuthenticated=false when no session exists", async () => {
  render(
    <AuthProvider>
      <TestConsumer />
    </AuthProvider>
  );

  await waitFor(() => {
    expect(screen.getByTestId("is-auth").textContent).toBe("false");
  });
  expect(screen.getByTestId("user").textContent).toBe("none");
});

test("login sets user and token; logout clears them", async () => {
  const mockUser = {
    user_id: 1,
    full_name: "Admin User",
    roles: ["admin"],
    preferred_language: "en",
    effective_privileges: ["receiving.view", "inventory.view"],
  };

  // First call is /api/auth/me (returns no session), second is /api/auth/login
  (global.fetch as jest.Mock)
    .mockResolvedValueOnce({ ok: false, json: async () => ({}) })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access_token: "tok123", user: mockUser }),
    })
    .mockResolvedValueOnce({ ok: true, json: async () => ({}) }); // logout

  function LoginLogoutConsumer() {
    const { isAuthenticated, user, login, logout, hasPrivilege } = useAuth();
    return (
      <div>
        <span data-testid="is-auth">{String(isAuthenticated)}</span>
        <span data-testid="user">{user?.full_name ?? "none"}</span>
        <span data-testid="priv">{String(hasPrivilege("receiving.view"))}</span>
        <button onClick={() => login({ username: "admin", password: "admin123" })}>
          login
        </button>
        <button onClick={() => logout()}>logout</button>
      </div>
    );
  }

  render(
    <AuthProvider>
      <LoginLogoutConsumer />
    </AuthProvider>
  );

  // Wait for initial mount effect to settle
  await waitFor(() => expect(screen.getByTestId("is-auth").textContent).toBe("false"));

  // Login
  await act(async () => {
    screen.getByText("login").click();
  });

  await waitFor(() => {
    expect(screen.getByTestId("is-auth").textContent).toBe("true");
    expect(screen.getByTestId("user").textContent).toBe("Admin User");
    expect(screen.getByTestId("priv").textContent).toBe("true");
  });

  // Logout
  await act(async () => {
    screen.getByText("logout").click();
  });

  await waitFor(() => {
    expect(screen.getByTestId("is-auth").textContent).toBe("false");
    expect(screen.getByTestId("user").textContent).toBe("none");
  });
});

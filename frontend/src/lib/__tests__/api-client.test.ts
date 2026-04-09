import axios from "axios";
import { apiClient, setAuthToken, registerLogoutHandler, registerNavigateHandler } from "../api-client";

// Reset axios defaults between tests
beforeEach(() => {
  delete apiClient.defaults.headers.common["Authorization"];
  jest.resetAllMocks();
});

test("setAuthToken adds Bearer Authorization header to apiClient", () => {
  setAuthToken("my-secret-token");
  expect(apiClient.defaults.headers.common["Authorization"]).toBe(
    "Bearer my-secret-token"
  );

  setAuthToken(null);
  expect(apiClient.defaults.headers.common["Authorization"]).toBeUndefined();
});

test("401 response triggers logout handler and navigates to /login", async () => {
  const logoutFn = jest.fn();
  const navigateFn = jest.fn();
  registerLogoutHandler(logoutFn);
  registerNavigateHandler(navigateFn);

  // Create an adapter that returns a 401
  const adapter401 = async () => {
    const err = new axios.AxiosError("Request failed with status code 401");
    (err as Record<string, unknown>).response = { status: 401, data: {}, headers: {}, config: {} };
    throw err;
  };

  // Temporarily swap the adapter
  const originalAdapter = apiClient.defaults.adapter;
  apiClient.defaults.adapter = adapter401 as typeof originalAdapter;

  try {
    await apiClient.get("/test");
  } catch {
    // expected to throw
  }

  expect(logoutFn).toHaveBeenCalledTimes(1);
  expect(navigateFn).toHaveBeenCalledWith("/login");

  // Restore adapter
  apiClient.defaults.adapter = originalAdapter;
});

import axios from "axios";
import { SESSION_EXPIRED_REASON } from "@/src/lib/auth-constants";

export function getResponseStatus(err: unknown): number | undefined {
  return axios.isAxiosError(err) ? err.response?.status : undefined;
}

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    "Content-Type": "application/json",
  },
});

// Attach Bearer token from current auth state
export function setAuthToken(token: string | null) {
  if (token) {
    apiClient.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  } else {
    delete apiClient.defaults.headers.common["Authorization"];
  }
}

type LogoutFn = () => void;
type NavigateFn = (path: string) => void;

let _logoutFn: LogoutFn | null = null;
let _navigateFn: NavigateFn = (path: string) => {
  if (typeof window !== "undefined") {
    window.location.href = path;
  }
};

export function registerLogoutHandler(fn: LogoutFn) {
  _logoutFn = fn;
}

export function registerNavigateHandler(fn: NavigateFn) {
  _navigateFn = fn;
}

// 401 / "Not authenticated" 403 interceptor → logout + redirect
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;

    const isUnauthenticated =
      status === 401 ||
      (status === 403 && detail === "Not authenticated");

    if (isUnauthenticated) {
      if (_logoutFn) _logoutFn();
      _navigateFn(`/login?reason=${SESSION_EXPIRED_REASON}`);
    }
    return Promise.reject(error);
  }
);

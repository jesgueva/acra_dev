export interface User {
  id: number;
  username: string;
  full_name: string;
  roles: string[];
  preferred_language: string;
  production_line: string | null;
  status: string;
  created_at: string;
}

export interface Role {
  id: number;
  role_name: string;
  description: string | null;
}

export interface UserListResponse {
  total: number;
  page: number;
  page_size: number;
  results: User[];
}

export interface RoleListResponse {
  results: Role[];
}

export interface UserFilterState {
  status: string;
  role: string;
}

export const ALL = "all";

export const DEFAULT_USER_FILTERS: UserFilterState = {
  status: ALL,
  role: ALL,
};

export function userFiltersToParams(
  filters: UserFilterState,
  page: number,
  pageSize: number
): URLSearchParams {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  if (filters.status !== ALL) params.set("status", filters.status);
  if (filters.role !== ALL) params.set("role", filters.role);
  return params;
}

export interface AuditLog {
  id: number;
  user_id: number | null;
  username: string | null;
  action: string;
  entity_type: string;
  entity_id: number | null;
  details: Record<string, unknown> | null;
  timestamp: string;
}

export interface AuditListResponse {
  total: number;
  page: number;
  page_size: number;
  results: AuditLog[];
}

export interface AuditFilterState {
  action: string;
  entity_type: string;
}

export const DEFAULT_AUDIT_FILTERS: AuditFilterState = {
  action: "",
  entity_type: "",
};

/** Ticket contract: the audit log pages at 50 rows. */
export const AUDIT_PAGE_SIZE = 50;

export function auditFiltersToParams(
  filters: AuditFilterState,
  page: number,
  pageSize: number = AUDIT_PAGE_SIZE
): URLSearchParams {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  if (filters.action.trim()) params.set("action", filters.action.trim());
  if (filters.entity_type.trim()) params.set("entity_type", filters.entity_type.trim());
  return params;
}

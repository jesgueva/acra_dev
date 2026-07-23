export const PRIVILEGES = {
  RECEIVING_VIEW: "receiving.view",
  INVENTORY_VIEW: "inventory.view",
  WORK_ORDERS_VIEW: "work_orders.view",
  SHIPPING_VIEW: "shipping.view",
  SHIPPING_CREATE: "shipping.create",
  USERS_MANAGE: "users.manage",
  AUDIT_VIEW: "audit.view",
  MASTER_DATA_VIEW: "master_data.view",
  MASTER_DATA_MANAGE: "master_data.manage",
} as const;

export type Privilege = (typeof PRIVILEGES)[keyof typeof PRIVILEGES];

/**
 * Role identifiers exactly as stored in `roles.role_name` and returned by
 * `POST /auth/login` — matched against `user.roles`, never displayed.
 *
 * Must stay in sync with the seed in migration `001_initial_schema`. Use
 * `roleLabel()` or the `users.roles.*` messages for anything user-facing.
 */
export const ROLES = {
  ADMIN: "company_admin",
  SUPERVISOR: "production_supervisor",
  CLERK: "receiving_clerk",
  OPERATOR: "machine_operator",
} as const;

export type Role = (typeof ROLES)[keyof typeof ROLES];

export const ROLE_SLUGS: Role[] = [
  ROLES.ADMIN,
  ROLES.SUPERVISOR,
  ROLES.CLERK,
  ROLES.OPERATOR,
];

/** Fallback display name for a role slug: "machine_operator" -> "Machine Operator". */
export function roleLabel(slug: string): string {
  return slug
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

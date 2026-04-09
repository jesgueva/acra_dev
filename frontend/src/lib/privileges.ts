export const PRIVILEGES = {
  RECEIVING_VIEW: "receiving.view",
  INVENTORY_VIEW: "inventory.view",
  WORK_ORDERS_VIEW: "work_orders.view",
  WORK_ORDERS_CREATE: "work_orders.create",
  WORK_ORDERS_ALLOCATE: "work_orders.allocate",
  WORK_ORDERS_ASSIGN: "work_orders.assign",
  WORK_ORDERS_STATUS: "work_orders.status_update",
  WORK_ORDERS_SEQUENCE: "work_orders.sequence",
  USERS_MANAGE: "users.manage",
  AUDIT_VIEW: "audit.view",
} as const;

export type Privilege = (typeof PRIVILEGES)[keyof typeof PRIVILEGES];

export const ROLES = {
  ADMIN: "Admin",
  SUPERVISOR: "Supervisor",
  CLERK: "Clerk",
  OPERATOR: "Machine Operator",
} as const;

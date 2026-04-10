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

export const ROLES = {
  ADMIN: "Admin",
  SUPERVISOR: "Supervisor",
  CLERK: "Clerk",
  OPERATOR: "Machine Operator",
} as const;

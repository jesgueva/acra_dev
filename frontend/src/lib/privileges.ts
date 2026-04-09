export const PRIVILEGES = {
  RECEIVING_VIEW: "receiving.view",
  INVENTORY_VIEW: "inventory.view",
  WORK_ORDERS_VIEW: "work_orders.view",
  USERS_MANAGE: "users.manage",
  AUDIT_VIEW: "audit.view",
} as const;

export type Privilege = (typeof PRIVILEGES)[keyof typeof PRIVILEGES];

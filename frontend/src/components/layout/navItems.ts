import {
  Truck,
  Boxes,
  ClipboardList,
  Users,
  ScrollText,
  Database,
  FileText,
  type LucideIcon,
} from "lucide-react";
import { PRIVILEGES } from "@/src/lib/privileges";

export interface NavItem {
  /** Key into the `nav` message namespace. */
  key:
    | "receiving"
    | "inventory"
    | "workOrders"
    | "deliveryNotes"
    | "contacts"
    | "users"
    | "audit";
  /** Path under `/[locale]/`. */
  path: string;
  icon: LucideIcon;
  privilege: string;
}

/**
 * The navigation, defined once.
 *
 * Both the desktop sidebar and the mobile drawer render from this list, so a module can never
 * appear in one and not the other — and, more importantly, a privilege filter can never be applied
 * in one and forgotten in the other.
 *
 * Shipping is deliberately absent: `shipping.view` / `shipping.create` are granted to no role
 * (ACR-35), so the page 403s for everyone and linking to it would only lead to a dead end.
 */
export const NAV_ITEMS: NavItem[] = [
  { key: "receiving", path: "receiving", icon: Truck, privilege: PRIVILEGES.RECEIVING_VIEW },
  { key: "inventory", path: "inventory", icon: Boxes, privilege: PRIVILEGES.INVENTORY_VIEW },
  { key: "workOrders", path: "work-orders", icon: ClipboardList, privilege: PRIVILEGES.WORK_ORDERS_VIEW },
  // Gated on deliveries.view to match the API — not shipping.view, which is granted to no role
  // until ACR-35 and would therefore hide the link from everyone.
  { key: "deliveryNotes", path: "delivery-notes", icon: FileText, privilege: PRIVILEGES.DELIVERIES_VIEW },
  { key: "contacts", path: "master-data/contacts", icon: Database, privilege: PRIVILEGES.RECEIVING_VIEW },
  { key: "users", path: "users", icon: Users, privilege: PRIVILEGES.USERS_MANAGE },
  { key: "audit", path: "audit", icon: ScrollText, privilege: PRIVILEGES.AUDIT_VIEW },
];

import {
  Truck,
  Boxes,
  ClipboardList,
  Users,
  ScrollText,
  Database,
  FileText,
  PackageCheck,
  type LucideIcon,
} from "lucide-react";
import { PRIVILEGES } from "@/src/lib/privileges";

export interface NavItem {
  /** Key into the `nav` message namespace. */
  key:
    | "receiving"
    | "inventory"
    | "workOrders"
    | "shippingNav"
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
 */
export const NAV_ITEMS: NavItem[] = [
  { key: "receiving", path: "receiving", icon: Truck, privilege: PRIVILEGES.RECEIVING_VIEW },
  { key: "inventory", path: "inventory", icon: Boxes, privilege: PRIVILEGES.INVENTORY_VIEW },
  { key: "workOrders", path: "work-orders", icon: ClipboardList, privilege: PRIVILEGES.WORK_ORDERS_VIEW },
  // ACR-35 (migration 013) grants shipping.view to company_admin, so gating on it no longer
  // hides the link from every role the way it did when this list was first written.
  { key: "shippingNav", path: "shipping", icon: PackageCheck, privilege: PRIVILEGES.SHIPPING_VIEW },
  // Gated on deliveries.view to match the API, which admits deliveries.view OR shipping.view.
  { key: "deliveryNotes", path: "delivery-notes", icon: FileText, privilege: PRIVILEGES.DELIVERIES_VIEW },
  { key: "contacts", path: "master-data/contacts", icon: Database, privilege: PRIVILEGES.RECEIVING_VIEW },
  { key: "users", path: "users", icon: Users, privilege: PRIVILEGES.USERS_MANAGE },
  { key: "audit", path: "audit", icon: ScrollText, privilege: PRIVILEGES.AUDIT_VIEW },
];

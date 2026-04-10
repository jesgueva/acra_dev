import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Users, UserPlus, Shield, KeyRound, UserX } from "lucide-react";
import {
  ComingSoonBadge,
  ModuleBanner,
  FeatureGrid,
  RequirementsBar,
  SectionLabel,
  type PlaceholderFeature,
} from "@/src/components/layout/ModulePlaceholder";

const FEATURES: PlaceholderFeature[] = [
  {
    icon: UserPlus,
    title: "Create User Accounts",
    description: "Add new users with full name, username, and temporary password.",
  },
  {
    icon: Shield,
    title: "Role Assignment",
    description: "Assign one or more roles: Admin, Receiving Clerk, Production Supervisor, Machine Operator.",
  },
  {
    icon: KeyRound,
    title: "Privilege-Based Access",
    description: "Users holding multiple roles receive the union of all privileges granted by each role.",
  },
  {
    icon: UserX,
    title: "Account Deactivation",
    description: "Deactivate accounts while preserving audit history. At least one Admin must remain active.",
  },
];

const ROLES = [
  { name: "Company Admin", privileges: "All system privileges" },
  { name: "Receiving / Shipping Clerk", privileges: "PRV-001 · PRV-002 · PRV-003 · PRV-004" },
  { name: "Production Supervisor", privileges: "PRV-004 · PRV-007 · PRV-009–012" },
  { name: "Machine Operator", privileges: "PRV-009" },
];

const REQUIREMENTS = ["FR-035", "FR-036", "FR-037", "FR-038", "FR-039"];

export default async function UsersPage() {
  const t = await getTranslations("users");
  const tCommon = await getTranslations("common");

  return (
    <div className="flex flex-col flex-1">
      <PageHeader title={t("title")} description={t("subtitle")}>
        <ComingSoonBadge label={tCommon("comingSoon")} />
      </PageHeader>

      <div className="flex-1 space-y-6 p-6">
        <ModuleBanner
          icon={Users}
          title="User Management Module"
          description={`${tCommon("underDevelopment")} Full RBAC administration — create accounts, assign roles, and control system access across all four user types.`}
        />

        <Separator />

        <div>
          <SectionLabel>System Roles</SectionLabel>
          <Card>
            {ROLES.map((role, i) => (
              <div key={role.name}>
                <div className="flex items-center justify-between gap-4 px-5 py-3.5">
                  <p className="text-sm font-medium text-foreground">{role.name}</p>
                  <p className="font-mono text-xs text-muted-foreground">{role.privileges}</p>
                </div>
                {i < ROLES.length - 1 && <Separator />}
              </div>
            ))}
          </Card>
        </div>

        <Separator />

        <FeatureGrid features={FEATURES} />

        <Separator />

        <RequirementsBar requirements={REQUIREMENTS} />
      </div>
    </div>
  );
}

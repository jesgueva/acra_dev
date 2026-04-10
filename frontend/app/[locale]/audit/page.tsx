import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollText, Filter, User, Clock, Database } from "lucide-react";
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
    icon: User,
    title: "User Action Tracking",
    description: "Every data-modifying action is recorded with the performing user and timestamp.",
  },
  {
    icon: Clock,
    title: "Login & Session Events",
    description: "All login, logout, and session expiration events are logged for security review.",
  },
  {
    icon: Database,
    title: "Entity Change Log",
    description: "Track changes to inventory, work orders, and user accounts with before/after detail.",
  },
  {
    icon: Filter,
    title: "Filterable Log View",
    description: "Filter by user, action type, entity, or date range to investigate specific events.",
  },
];

const SAMPLE_ACTIONS = [
  { action: "inventory.adjust", entity: "InventoryItem", user: "admin" },
  { action: "workorder.create", entity: "WorkOrder", user: "admin" },
  { action: "user.login", entity: "Session", user: "supervisor1" },
  { action: "receiving.create", entity: "Delivery", user: "clerk1" },
];

const REQUIREMENTS = ["FR-012", "FR-039", "NFR-009"];

export default async function AuditPage() {
  const t = await getTranslations("audit");
  const tCommon = await getTranslations("common");

  return (
    <div className="flex flex-col flex-1">
      <PageHeader title={t("title")} description={t("subtitle")}>
        <ComingSoonBadge label={tCommon("comingSoon")} />
      </PageHeader>

      <div className="flex-1 space-y-6 p-6">
        <ModuleBanner
          icon={ScrollText}
          title="Audit Log Module"
          description={`${tCommon("underDevelopment")} All system events are already being recorded. The full audit viewer — with filtering, export, and compliance reporting — will be available here.`}
        />

        <Separator />

        <div>
          <SectionLabel>Log Structure Preview</SectionLabel>
          <Card>
            <div className="grid grid-cols-3 gap-4 border-b border-border bg-muted/30 px-5 py-3">
              {["Action", "Entity", "User"].map((col) => (
                <p key={col} className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  {col}
                </p>
              ))}
            </div>
            {SAMPLE_ACTIONS.map((row, i) => (
              <div key={row.action}>
                <div className="grid grid-cols-3 gap-4 px-5 py-3.5 items-center">
                  <Badge variant="outline" className="font-mono text-xs w-fit">
                    {row.action}
                  </Badge>
                  <p className="text-xs text-muted-foreground">{row.entity}</p>
                  <p className="text-xs text-muted-foreground">{row.user}</p>
                </div>
                {i < SAMPLE_ACTIONS.length - 1 && <Separator />}
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

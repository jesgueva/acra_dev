import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ClipboardList, Plus, GitBranch, Package, ArrowRight } from "lucide-react";
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
    icon: Plus,
    title: "Create Work Orders",
    description: "Define product, quantity, required materials, priority, and target completion date.",
  },
  {
    icon: GitBranch,
    title: "Lifecycle Tracking",
    description: "Track orders through: Created → Materials Allocated → In Production → Completed → Ready for Shipment.",
  },
  {
    icon: Package,
    title: "Material Allocation",
    description: "Automatically reserve raw materials from inventory when a work order is activated.",
  },
  {
    icon: ArrowRight,
    title: "Production Line Assignment",
    description: "Assign and prioritize work orders across the five production lines.",
  },
];

const STATUS_FLOW = ["Created", "Materials Allocated", "In Production", "Completed", "Ready for Shipment"];
const REQUIREMENTS = ["FR-013", "FR-014", "FR-015", "FR-016", "FR-017", "FR-018", "FR-019", "FR-021"];

export default async function WorkOrdersPage() {
  const t = await getTranslations("workOrders");
  const tCommon = await getTranslations("common");

  return (
    <div className="flex flex-col flex-1">
      <PageHeader title={t("title")} description={t("subtitle")}>
        <ComingSoonBadge label={tCommon("comingSoon")} />
      </PageHeader>

      <div className="flex-1 space-y-6 p-6">
        <ModuleBanner
          icon={ClipboardList}
          title="Work Order Management Module"
          description={`${tCommon("underDevelopment")} Replaces manual order spreadsheets with a digital production lifecycle system — from creation through to shipment readiness.`}
        />

        <Separator />

        <div>
          <SectionLabel>Order Lifecycle</SectionLabel>
          <div className="flex flex-wrap items-center gap-1.5">
            {STATUS_FLOW.map((status, i) => (
              <div key={status} className="flex items-center gap-1.5">
                <Badge variant="secondary" className="font-medium">
                  {status}
                </Badge>
                {i < STATUS_FLOW.length - 1 && (
                  <ArrowRight className="h-3.5 w-3.5 text-muted-foreground/40" />
                )}
              </div>
            ))}
          </div>
        </div>

        <Separator />

        <FeatureGrid features={FEATURES} />

        <Separator />

        <RequirementsBar requirements={REQUIREMENTS} />
      </div>
    </div>
  );
}

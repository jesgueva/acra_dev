import { getTranslations } from "next-intl/server";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Separator } from "@/components/ui/separator";
import { Truck, ScanLine, FileText, Search, PackageCheck } from "lucide-react";
import {
  ComingSoonBadge,
  ModuleBanner,
  FeatureGrid,
  RequirementsBar,
  type PlaceholderFeature,
} from "@/src/components/layout/ModulePlaceholder";

const FEATURES: PlaceholderFeature[] = [
  {
    icon: ScanLine,
    title: "OCR Document Scanning",
    description: "Photograph or upload bills of lading for automatic data extraction.",
  },
  {
    icon: FileText,
    title: "Manual Entry",
    description: "Enter delivery information manually when documents are unavailable.",
  },
  {
    icon: PackageCheck,
    title: "Automatic Inventory Creation",
    description: "Confirmed deliveries instantly generate inventory records with lot traceability.",
  },
  {
    icon: Search,
    title: "Delivery History",
    description: "Searchable log of all receiving records with supplier and BOL reference.",
  },
];

const REQUIREMENTS = ["FR-001", "FR-002", "FR-003", "FR-004", "FR-005"];

export default async function ReceivingPage() {
  const t = await getTranslations("receiving");
  const tCommon = await getTranslations("common");

  return (
    <div className="flex flex-col flex-1">
      <PageHeader title={t("title")} description={t("subtitle")}>
        <ComingSoonBadge label={tCommon("comingSoon")} />
      </PageHeader>

      <div className="flex-1 space-y-6 p-6">
        <ModuleBanner
          icon={Truck}
          title="Receiving & Intake Module"
          description={`${tCommon("underDevelopment")} This module will replace manual BOL transcription with an OCR-powered workflow, reducing data entry time by 60–70%.`}
        />

        <Separator />

        <FeatureGrid features={FEATURES} />

        <Separator />

        <RequirementsBar requirements={REQUIREMENTS} />
      </div>
    </div>
  );
}

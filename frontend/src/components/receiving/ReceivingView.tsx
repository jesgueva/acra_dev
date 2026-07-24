"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ScanLine } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { PageHeader } from "@/src/components/layout/PageHeader";
import OCRUploader from "./OCRUploader";
import NewDeliveryForm from "./NewDeliveryForm";
import DeliveryList from "./DeliveryList";
import type { OCRResult } from "./OCRUploader";

function buildHighlightedFields(result: OCRResult): string[] {
  const fields: string[] = [];
  if (result.supplier) fields.push("supplier");
  if (result.carrier) fields.push("carrier");
  if (result.bol_reference) fields.push("bol_reference");
  if (result.delivery_date) fields.push("delivery_date");
  result.items?.forEach((_, i) => {
    fields.push(`items.${i}.product_id`);
    fields.push(`items.${i}.description`);
  });
  return fields;
}

export default function ReceivingView() {
  const t = useTranslations("receiving");

  const [refetchCount, setRefetchCount] = useState(0);
  const [ocrResult, setOcrResult] = useState<Partial<OCRResult> | undefined>();
  const [highlightedFields, setHighlightedFields] = useState<string[]>([]);

  function handleOCRResult(result: OCRResult) {
    setOcrResult(result);
    setHighlightedFields(buildHighlightedFields(result));
  }

  function handleFormSuccess() {
    setRefetchCount((n) => n + 1);
    setOcrResult(undefined);
    setHighlightedFields([]);
  }

  return (
    <div className="flex flex-col flex-1">
      <PageHeader title={t("title")} description={t("subtitle")} />

      <div className="flex-1 p-6">
        <div className="grid grid-cols-1 lg:grid-cols-[600px_1fr] gap-6 items-start">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <ScanLine className="h-4 w-4 text-muted-foreground" />
                <CardTitle className="text-base">{t("newDelivery")}</CardTitle>
              </div>
              <CardDescription>{t("ocrHint")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <OCRUploader onOCRResult={handleOCRResult} />
              <Separator />
              <NewDeliveryForm
                onSuccess={handleFormSuccess}
                initialValues={ocrResult}
                ocrHighlightedFields={highlightedFields}
              />
            </CardContent>
          </Card>

          <div className="space-y-4">
            <h2 className="text-base font-semibold">{t("deliveryHistory")}</h2>
            <DeliveryList refetch={refetchCount} />
          </div>
        </div>
      </div>
    </div>
  );
}

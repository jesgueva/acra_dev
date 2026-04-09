"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import OCRUploader, { type OCRResult } from "@/src/components/receiving/OCRUploader";
import NewDeliveryForm from "@/src/components/receiving/NewDeliveryForm";
import DeliveryList from "@/src/components/receiving/DeliveryList";

export default function ReceivingPage() {
  const t = useTranslations("receiving");

  const [ocrValues, setOcrValues] = useState<Partial<OCRResult> | undefined>();
  const [ocrHighlightedFields, setOcrHighlightedFields] = useState<string[]>([]);
  const [refetch, setRefetch] = useState(0);

  function handleOCRResult(result: OCRResult) {
    setOcrValues(result);
    // Mark all top-level non-empty fields plus item fields as highlighted
    const highlighted: string[] = [];
    if (result.supplier) highlighted.push("supplier");
    if (result.bol_number) highlighted.push("bol_number");
    result.items?.forEach((_, i) => {
      highlighted.push(`items.${i}.item_name`);
      highlighted.push(`items.${i}.lot_batch_number`);
      highlighted.push(`items.${i}.quantity`);
      highlighted.push(`items.${i}.unit`);
    });
    setOcrHighlightedFields(highlighted);
  }

  function handleDeliverySuccess() {
    toast.success(t("ocrSuccess"));
    setOcrValues(undefined);
    setOcrHighlightedFields([]);
    setRefetch((n) => n + 1);
  }

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-semibold">{t("title")}</h1>

      {/* OCR Upload */}
      <Card>
        <CardContent className="pt-6">
          <OCRUploader onOCRResult={handleOCRResult} />
        </CardContent>
      </Card>

      {/* New Delivery Form */}
      <Card>
        <CardHeader>
          <CardTitle>{t("submit")}</CardTitle>
        </CardHeader>
        <CardContent>
          <NewDeliveryForm
            onSuccess={handleDeliverySuccess}
            initialValues={ocrValues}
            ocrHighlightedFields={ocrHighlightedFields}
          />
        </CardContent>
      </Card>

      {/* Delivery List */}
      <Card>
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <DeliveryList refetch={refetch} />
        </CardContent>
      </Card>
    </div>
  );
}

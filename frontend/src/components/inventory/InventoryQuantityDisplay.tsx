"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { toDisplay } from "@/src/lib/qty";

interface InventoryQuantityDisplayProps {
  quantityOnHand: number;
  isTriggered: boolean;
  lowStockBadgeTestId?: string;
}

export function InventoryQuantityDisplay({
  quantityOnHand,
  isTriggered,
  lowStockBadgeTestId,
}: InventoryQuantityDisplayProps) {
  const t = useTranslations("inventory");

  return (
    <span className="inline-flex items-center gap-2">
      {toDisplay(quantityOnHand)}
      {isTriggered && (
        <Badge
          variant="destructive"
          className="text-xs"
          data-testid={lowStockBadgeTestId}
        >
          {t("lowStock")}
        </Badge>
      )}
    </span>
  );
}

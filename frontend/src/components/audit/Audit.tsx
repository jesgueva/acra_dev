"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { apiClient } from "@/src/lib/api-client";
import { AuditLogTable } from "./AuditLogTable";
import {
  AUDIT_PAGE_SIZE,
  AuditFilterState,
  AuditListResponse,
  DEFAULT_AUDIT_FILTERS,
  auditFiltersToParams,
} from "./types";

export function Audit() {
  const t = useTranslations("audit");

  const [filters, setFilters] = useState<AuditFilterState>(DEFAULT_AUDIT_FILTERS);
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery<AuditListResponse>({
    queryKey: ["audit-logs", filters, page],
    queryFn: async () => {
      const params = auditFiltersToParams(filters, page);
      const res = await apiClient.get<AuditListResponse>(`/audit-logs?${params}`);
      return res.data;
    },
  });

  const logs = useMemo(() => data?.results ?? [], [data]);
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / AUDIT_PAGE_SIZE));

  const updateFilter = useCallback((key: keyof AuditFilterState, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
  }, []);

  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")} />

      <div className="space-y-6 p-6">
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1">
            <Label htmlFor="action-filter">{t("colAction")}</Label>
            <Input
              id="action-filter"
              className="w-56"
              value={filters.action}
              placeholder={t("actionPlaceholder")}
              onChange={(e) => updateFilter("action", e.target.value)}
              data-testid="action-filter"
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="entity-filter">{t("colEntity")}</Label>
            <Input
              id="entity-filter"
              className="w-56"
              value={filters.entity_type}
              placeholder={t("entityPlaceholder")}
              onChange={(e) => updateFilter("entity_type", e.target.value)}
              data-testid="entity-filter"
            />
          </div>
        </div>

        <AuditLogTable logs={logs} loading={isLoading} />

        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground" data-testid="audit-count">
            {t("resultCount", { count: total })}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || isLoading}
              onClick={() => setPage((p) => p - 1)}
            >
              {t("previous")}
            </Button>
            <span className="text-sm">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages || isLoading}
              onClick={() => setPage((p) => p + 1)}
            >
              {t("next")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

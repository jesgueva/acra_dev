"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { apiClient } from "@/src/lib/api-client";
import { roleLabel } from "@/src/lib/privileges";
import { UserTable } from "./UserTable";
import { UserForm } from "./UserForm";
import { DeactivateConfirmDialog } from "./DeactivateConfirmDialog";
import {
  ALL,
  DEFAULT_USER_FILTERS,
  Role,
  RoleListResponse,
  User,
  UserFilterState,
  UserListResponse,
  userFiltersToParams,
} from "./types";

const PAGE_SIZE = 20;

export function Users() {
  const t = useTranslations("users");
  const queryClient = useQueryClient();

  const [filters, setFilters] = useState<UserFilterState>(DEFAULT_USER_FILTERS);
  const [page, setPage] = useState(1);
  const [formTarget, setFormTarget] = useState<User | "new" | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<User | null>(null);

  const { data, isLoading } = useQuery<UserListResponse>({
    queryKey: ["users", filters, page],
    queryFn: async () => {
      const params = userFiltersToParams(filters, page, PAGE_SIZE);
      const res = await apiClient.get<UserListResponse>(`/users?${params}`);
      return res.data;
    },
  });

  // Roles are fixed by migration, so they can be cached indefinitely.
  const { data: rolesData } = useQuery<RoleListResponse>({
    queryKey: ["roles"],
    queryFn: async () => {
      const res = await apiClient.get<RoleListResponse>("/roles");
      return res.data;
    },
    staleTime: Infinity,
  });

  const users = useMemo(() => data?.results ?? [], [data]);
  const roles: Role[] = useMemo(() => rolesData?.results ?? [], [rolesData]);
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["users"] }),
    [queryClient]
  );

  const updateFilter = useCallback((key: keyof UserFilterState, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(1);
  }, []);

  return (
    <div>
      <PageHeader title={t("title")} description={t("subtitle")}>
        <Button onClick={() => setFormTarget("new")} data-testid="new-user-button">
          <UserPlus className="h-4 w-4" />
          {t("createUser")}
        </Button>
      </PageHeader>

      <div className="space-y-6 p-6">
        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1">
            <Label htmlFor="status-filter">{t("colStatus")}</Label>
            <Select
              value={filters.status}
              onValueChange={(v) => updateFilter("status", v)}
            >
              <SelectTrigger id="status-filter" className="w-44" data-testid="status-filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>{t("allStatuses")}</SelectItem>
                <SelectItem value="active">{t("statusActive")}</SelectItem>
                <SelectItem value="inactive">{t("statusInactive")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <Label htmlFor="role-filter">{t("colRoles")}</Label>
            <Select value={filters.role} onValueChange={(v) => updateFilter("role", v)}>
              <SelectTrigger id="role-filter" className="w-56" data-testid="role-filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>{t("allRoles")}</SelectItem>
                {roles.map((role) => (
                  <SelectItem key={role.id} value={role.role_name}>
                    {roleLabel(role.role_name)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <UserTable
          users={users}
          loading={isLoading}
          onEdit={setFormTarget}
          onDeactivate={setDeactivateTarget}
        />

        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground" data-testid="user-count">
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

      <UserForm
        target={formTarget}
        roles={roles}
        onClose={() => setFormTarget(null)}
        onSuccess={invalidate}
      />

      <DeactivateConfirmDialog
        user={deactivateTarget}
        onClose={() => setDeactivateTarget(null)}
        onSuccess={invalidate}
      />
    </div>
  );
}

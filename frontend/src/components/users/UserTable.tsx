"use client";

import { useTranslations } from "next-intl";
import { Pencil, UserX } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import { DataTable } from "@/src/components/layout/DataTable";
import { roleLabel } from "@/src/lib/privileges";
import { User } from "./types";

interface UserTableProps {
  users: User[];
  loading: boolean;
  onEdit: (user: User) => void;
  onDeactivate: (user: User) => void;
}

export function UserTable({
  users,
  loading,
  onEdit,
  onDeactivate,
}: UserTableProps) {
  const t = useTranslations("users");

  const columns = [
    t("colUsername"),
    t("colFullName"),
    t("colRoles"),
    t("colProductionLine"),
    t("colStatus"),
    t("colActions"),
  ];

  return (
    <DataTable
      columns={columns}
      loading={loading}
      isEmpty={users.length === 0}
      emptyMessage={t("noUsers")}
      data-testid="user-table"
    >
      {users.map((user) => (
        <TableRow key={user.id} data-testid={`user-row-${user.id}`}>
          <TableCell className="font-medium">{user.username}</TableCell>
          <TableCell>{user.full_name}</TableCell>
          <TableCell>
            <div className="flex flex-wrap gap-1">
              {user.roles.length === 0 ? (
                <span className="text-muted-foreground">—</span>
              ) : (
                user.roles.map((role) => (
                  <Badge key={role} variant="secondary">
                    {roleLabel(role)}
                  </Badge>
                ))
              )}
            </div>
          </TableCell>
          <TableCell>
            {user.production_line ?? <span className="text-muted-foreground">—</span>}
          </TableCell>
          <TableCell>
            <Badge
              variant={user.status === "active" ? "default" : "outline"}
              data-testid={`user-status-${user.id}`}
            >
              {user.status === "active" ? t("statusActive") : t("statusInactive")}
            </Badge>
          </TableCell>
          <TableCell>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onEdit(user)}
                aria-label={t("editUserAria", { username: user.username })}
                data-testid={`edit-user-${user.id}`}
              >
                <Pencil className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={user.status === "inactive"}
                onClick={() => onDeactivate(user)}
                aria-label={t("deactivateUserAria", { username: user.username })}
                data-testid={`deactivate-user-${user.id}`}
              >
                <UserX className="h-4 w-4" />
              </Button>
            </div>
          </TableCell>
        </TableRow>
      ))}
    </DataTable>
  );
}

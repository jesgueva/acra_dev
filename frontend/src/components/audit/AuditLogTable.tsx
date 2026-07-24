"use client";

import { Fragment, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { TableCell, TableRow } from "@/components/ui/table";
import { DataTable } from "@/src/components/layout/DataTable";
import { AuditLog } from "./types";

interface AuditLogTableProps {
  logs: AuditLog[];
  loading: boolean;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function AuditLogTable({ logs, loading }: AuditLogTableProps) {
  const t = useTranslations("audit");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const columns = [
    "",
    t("colTimestamp"),
    t("colUser"),
    t("colAction"),
    t("colEntity"),
  ];

  return (
    <DataTable
      columns={columns}
      loading={loading}
      isEmpty={logs.length === 0}
      emptyMessage={t("noEntries")}
      data-testid="audit-table"
    >
      {logs.map((log) => {
        const expanded = expandedId === log.id;
        return (
          <Fragment key={log.id}>
            <TableRow
              className="cursor-pointer"
              onClick={() => setExpandedId(expanded ? null : log.id)}
              data-testid={`audit-row-${log.id}`}
            >
              <TableCell className="w-8 text-muted-foreground">
                {expanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap">
                {formatTimestamp(log.timestamp)}
              </TableCell>
              <TableCell>
                {log.username ?? (
                  <span className="text-muted-foreground">
                    {log.user_id === null ? "—" : t("unknownUser", { id: log.user_id })}
                  </span>
                )}
              </TableCell>
              <TableCell>
                <Badge variant="secondary">{log.action}</Badge>
              </TableCell>
              <TableCell>
                {log.entity_type}
                {log.entity_id !== null && (
                  <span className="text-muted-foreground"> #{log.entity_id}</span>
                )}
              </TableCell>
            </TableRow>

            {expanded && (
              <TableRow data-testid={`audit-details-${log.id}`}>
                <TableCell colSpan={columns.length} className="bg-muted/40">
                  {log.details ? (
                    <pre className="overflow-x-auto text-xs whitespace-pre-wrap">
                      {JSON.stringify(log.details, null, 2)}
                    </pre>
                  ) : (
                    <p className="text-xs text-muted-foreground">{t("noDetails")}</p>
                  )}
                </TableCell>
              </TableRow>
            )}
          </Fragment>
        );
      })}
    </DataTable>
  );
}

import * as React from "react";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

interface DataTableProps {
  /** Column header labels in display order */
  columns: string[];
  /** TableRow elements rendered as the table body */
  children?: React.ReactNode;
  loading?: boolean;
  isEmpty?: boolean;
  emptyMessage?: string;
  className?: string;
  /** Forwarded to the inner <table> element for test selectors */
  "data-testid"?: string;
}

const SKELETON_ROWS = 4;

export function DataTable({
  columns,
  children,
  loading = false,
  isEmpty = false,
  emptyMessage = "No results.",
  className,
  "data-testid": testId,
}: DataTableProps) {
  return (
    <div className={cn("rounded-md border", className)}>
      <Table data-testid={testId}>
        <TableHeader>
          <TableRow>
            {columns.map((col) => (
              <TableHead key={col}>{col}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            Array.from({ length: SKELETON_ROWS }).map((_, i) => (
              <TableRow key={i}>
                {columns.map((col) => (
                  <TableCell key={col}>
                    <Skeleton className="h-4 w-full" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : isEmpty ? (
            <TableRow>
              <TableCell
                colSpan={columns.length}
                className="text-center py-8 text-muted-foreground"
              >
                {emptyMessage}
              </TableCell>
            </TableRow>
          ) : (
            children
          )}
        </TableBody>
      </Table>
    </div>
  );
}

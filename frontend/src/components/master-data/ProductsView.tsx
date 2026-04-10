"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { apiClient } from "@/src/lib/api-client";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Pencil, Trash2, Plus } from "lucide-react";

interface Contact {
  id: number;
  name: string;
  type: string;
}

interface Product {
  id: number;
  name: string;
  description: string | null;
  category: string;
  contact_id: number | null;
  created_at: string;
}

interface ProductListResponse {
  total: number;
  page: number;
  page_size: number;
  results: Product[];
}

interface ProductFormData {
  name: string;
  description: string;
  category: string;
  contact_id: string;
}

const EMPTY_FORM: ProductFormData = {
  name: "",
  description: "",
  category: "raw",
  contact_id: "",
};

const CATEGORY_VARIANTS: Record<string, "default" | "secondary" | "outline"> = {
  raw: "secondary",
  finished: "default",
  consumable: "outline",
};

export function ProductsView() {
  const t = useTranslations("products");
  const tc = useTranslations("common");
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [form, setForm] = useState<ProductFormData>(EMPTY_FORM);
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<ProductListResponse>({
    queryKey: ["products", page, categoryFilter],
    queryFn: () =>
      apiClient
        .get("/products", {
          params: {
            page,
            page_size: 20,
            ...(categoryFilter !== "all" ? { category: categoryFilter } : {}),
          },
        })
        .then((r) => r.data),
  });

  const { data: contactsData } = useQuery<{ results: Contact[] }>({
    queryKey: ["contacts-all"],
    queryFn: () => apiClient.get("/contacts", { params: { page_size: 100 } }).then((r) => r.data),
  });

  const contacts = contactsData?.results ?? [];

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiClient.post("/products", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] });
      setDialogOpen(false);
    },
    onError: () => setFormError(tc("error")),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      apiClient.patch(`/products/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] });
      setDialogOpen(false);
    },
    onError: () => setFormError(tc("error")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/products/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] });
      setDeleteDialogOpen(false);
    },
  });

  function openCreate() {
    setEditingProduct(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setDialogOpen(true);
  }

  function openEdit(p: Product) {
    setEditingProduct(p);
    setForm({
      name: p.name,
      description: p.description ?? "",
      category: p.category,
      contact_id: p.contact_id ? String(p.contact_id) : "",
    });
    setFormError(null);
    setDialogOpen(true);
  }

  function openDelete(p: Product) {
    setDeleteTarget(p);
    setDeleteDialogOpen(true);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const body = {
      name: form.name,
      description: form.description || null,
      category: form.category,
      contact_id: form.contact_id ? parseInt(form.contact_id, 10) : null,
    };
    if (editingProduct) {
      updateMutation.mutate({ id: editingProduct.id, body });
    } else {
      createMutation.mutate(body);
    }
  }

  function getContactName(contact_id: number | null): string {
    if (!contact_id) return "—";
    return contacts.find((c) => c.id === contact_id)?.name ?? String(contact_id);
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;
  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="space-y-6 p-6">
      <PageHeader title={t("title")} description={t("subtitle")}>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" />
          {t("newProduct")}
        </Button>
      </PageHeader>

      <div className="flex items-center gap-3">
        <Select value={categoryFilter} onValueChange={(v) => { setCategoryFilter(v); setPage(1); }}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Categories</SelectItem>
            <SelectItem value="raw">{t("raw")}</SelectItem>
            <SelectItem value="finished">{t("finished")}</SelectItem>
            <SelectItem value="consumable">{t("consumable")}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <Alert variant="destructive">
          <AlertDescription>{tc("error")}</AlertDescription>
        </Alert>
      )}

      {!isLoading && !isError && data && (
        <>
          <div className="rounded-md border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40">
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">{t("name")}</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">{t("category")}</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">{t("contact")}</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">{t("description")}</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.results.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                      {t("noProducts")}
                    </td>
                  </tr>
                ) : (
                  data.results.map((p) => (
                    <tr key={p.id} className="border-b border-border last:border-0 hover:bg-muted/20">
                      <td className="px-4 py-3 font-medium text-foreground">{p.name}</td>
                      <td className="px-4 py-3">
                        <Badge variant={CATEGORY_VARIANTS[p.category] ?? "outline"} className="capitalize">
                          {t(p.category as "raw" | "finished" | "consumable")}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{getContactName(p.contact_id)}</td>
                      <td className="max-w-xs px-4 py-3 text-muted-foreground">
                        <span className="line-clamp-1">{p.description ?? "—"}</span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button variant="ghost" size="sm" onClick={() => openEdit(p)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => openDelete(p)}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                Page {page} of {totalPages} — {data.total} total
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editingProduct ? tc("edit") : t("newProduct")}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="p-name">{t("name")} *</Label>
              <Input
                id="p-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                maxLength={200}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-category">{t("category")} *</Label>
              <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}>
                <SelectTrigger id="p-category">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="raw">{t("raw")}</SelectItem>
                  <SelectItem value="finished">{t("finished")}</SelectItem>
                  <SelectItem value="consumable">{t("consumable")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-contact">{t("contact")}</Label>
              <Select
                value={form.contact_id || "none"}
                onValueChange={(v) => setForm({ ...form, contact_id: v === "none" ? "" : v })}
              >
                <SelectTrigger id="p-contact">
                  <SelectValue placeholder="None" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  {contacts.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="p-description">{t("description")}</Label>
              <Input
                id="p-description"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            {formError && (
              <Alert variant="destructive">
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}
            <Separator />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                {tc("cancel")}
              </Button>
              <Button type="submit" disabled={isPending}>
                {isPending ? tc("loading") : tc("save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>{tc("delete")}</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t("deleteConfirm")}</p>
          {deleteTarget && (
            <p className="font-medium text-foreground">{deleteTarget.name}</p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              {tc("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
            >
              {deleteMutation.isPending ? tc("loading") : tc("delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

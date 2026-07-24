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
  client_code: string | null;
  address: string | null;
  phone: string | null;
  notes: string | null;
  created_at: string;
}

interface ContactListResponse {
  total: number;
  page: number;
  page_size: number;
  results: Contact[];
}

interface ContactFormData {
  name: string;
  type: string;
  client_code: string;
  address: string;
  phone: string;
  notes: string;
}

const EMPTY_FORM: ContactFormData = {
  name: "",
  type: "client",
  client_code: "",
  address: "",
  phone: "",
  notes: "",
};

const TYPE_VARIANTS: Record<string, "default" | "secondary" | "outline"> = {
  client: "default",
  provider: "secondary",
  carrier: "outline",
};

export function ContactsView() {
  const t = useTranslations("contacts");
  const tc = useTranslations("common");
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingContact, setEditingContact] = useState<Contact | null>(null);
  const [form, setForm] = useState<ContactFormData>(EMPTY_FORM);
  const [deleteTarget, setDeleteTarget] = useState<Contact | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery<ContactListResponse>({
    queryKey: ["contacts", page, typeFilter],
    queryFn: () =>
      apiClient
        .get("/contacts", {
          params: {
            page,
            page_size: 20,
            ...(typeFilter !== "all" ? { type: typeFilter } : {}),
          },
        })
        .then((r) => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiClient.post("/contacts", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
      setDialogOpen(false);
    },
    onError: () => setFormError(tc("error")),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
      apiClient.patch(`/contacts/${id}`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
      setDialogOpen(false);
    },
    onError: () => setFormError(tc("error")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => apiClient.delete(`/contacts/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["contacts"] });
      setDeleteDialogOpen(false);
    },
  });

  function openCreate() {
    setEditingContact(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setDialogOpen(true);
  }

  function openEdit(c: Contact) {
    setEditingContact(c);
    setForm({
      name: c.name,
      type: c.type,
      client_code: c.client_code ?? "",
      address: c.address ?? "",
      phone: c.phone ?? "",
      notes: c.notes ?? "",
    });
    setFormError(null);
    setDialogOpen(true);
  }

  function openDelete(c: Contact) {
    setDeleteTarget(c);
    setDeleteDialogOpen(true);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const body = {
      name: form.name,
      type: form.type,
      client_code: form.client_code || null,
      address: form.address || null,
      phone: form.phone || null,
      notes: form.notes || null,
    };
    if (editingContact) {
      updateMutation.mutate({ id: editingContact.id, body });
    } else {
      createMutation.mutate(body);
    }
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;
  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="space-y-6 p-6">
      <PageHeader title={t("title")} description={t("subtitle")}>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" />
          {t("newContact")}
        </Button>
      </PageHeader>

      <div className="flex items-center gap-3">
        <Select value={typeFilter} onValueChange={(v) => { setTypeFilter(v); setPage(1); }}>
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="client">{t("client")}</SelectItem>
            <SelectItem value="provider">{t("provider")}</SelectItem>
            <SelectItem value="carrier">{t("carrier")}</SelectItem>
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
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">{t("type")}</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">{t("clientCode")}</th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">{t("phone")}</th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.results.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                      {t("noContacts")}
                    </td>
                  </tr>
                ) : (
                  data.results.map((c) => (
                    <tr key={c.id} className="border-b border-border last:border-0 hover:bg-muted/20">
                      <td className="px-4 py-3 font-medium text-foreground">{c.name}</td>
                      <td className="px-4 py-3">
                        <Badge variant={TYPE_VARIANTS[c.type] ?? "outline"} className="capitalize">
                          {t(c.type as "client" | "provider" | "carrier")}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{c.client_code ?? "—"}</td>
                      <td className="px-4 py-3 text-muted-foreground">{c.phone ?? "—"}</td>
                      <td className="px-4 py-3 text-right">
                        <Button variant="ghost" size="sm" onClick={() => openEdit(c)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => openDelete(c)}>
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
            <DialogTitle>{editingContact ? tc("edit") : t("newContact")}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="name">{t("name")} *</Label>
              <Input
                id="name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                maxLength={200}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="type">{t("type")} *</Label>
              <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v })}>
                <SelectTrigger id="type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="client">{t("client")}</SelectItem>
                  <SelectItem value="provider">{t("provider")}</SelectItem>
                  <SelectItem value="carrier">{t("carrier")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="client_code">{t("clientCode")}</Label>
              <Input
                id="client_code"
                value={form.client_code}
                onChange={(e) => setForm({ ...form, client_code: e.target.value })}
                maxLength={50}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="phone">{t("phone")}</Label>
              <Input
                id="phone"
                value={form.phone}
                onChange={(e) => setForm({ ...form, phone: e.target.value })}
                maxLength={50}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="address">{t("address")}</Label>
              <Input
                id="address"
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
                maxLength={500}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="notes">{t("notes")}</Label>
              <Input
                id="notes"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
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

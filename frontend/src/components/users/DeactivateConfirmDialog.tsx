"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { apiClient, getResponseStatus } from "@/src/lib/api-client";
import { User } from "./types";

interface DeactivateConfirmDialogProps {
  user: User | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function DeactivateConfirmDialog({
  user,
  onClose,
  onSuccess,
}: DeactivateConfirmDialogProps) {
  const t = useTranslations("users");
  const tc = useTranslations("common");
  const [saving, setSaving] = useState(false);

  async function handleConfirm() {
    if (!user) return;
    setSaving(true);
    try {
      await apiClient.patch(`/users/${user.id}`, { status: "inactive" });
      toast.success(t("deactivateSuccess", { username: user.username }));
      onSuccess();
      onClose();
    } catch (err) {
      // 409 is the backend's last-admin guard — the account must stay active.
      toast.error(
        getResponseStatus(err) === 409 ? t("lastAdminError") : t("deactivateFailed")
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={user !== null} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      <DialogContent data-testid="deactivate-dialog">
        <DialogHeader>
          <DialogTitle>{t("deactivateTitle")}</DialogTitle>
          <DialogDescription>
            {t("deactivateConfirm", { username: user?.username ?? "" })}
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {tc("cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={saving}
            data-testid="confirm-deactivate"
          >
            {saving ? tc("saving") : t("deactivate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

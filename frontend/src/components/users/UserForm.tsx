"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiClient, getResponseStatus } from "@/src/lib/api-client";
import { ROLES, roleLabel } from "@/src/lib/privileges";
import { Role, User } from "./types";

interface UserFormProps {
  /** null = closed; a User = edit mode; "new" = create mode */
  target: User | "new" | null;
  roles: Role[];
  onClose: () => void;
  onSuccess: () => void;
}

export function UserForm({ target, roles, onClose, onSuccess }: UserFormProps) {
  const t = useTranslations("users");
  const tc = useTranslations("common");

  const isEdit = target !== null && target !== "new";
  const open = target !== null;

  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [language, setLanguage] = useState("en");
  const [productionLine, setProductionLine] = useState("");
  const [selectedRoleIds, setSelectedRoleIds] = useState<number[]>([]);

  const [usernameError, setUsernameError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Seed the fields whenever the dialog target changes.
  useEffect(() => {
    if (target === null) return;
    if (target === "new") {
      setUsername("");
      setFullName("");
      setPassword("");
      setLanguage("en");
      setProductionLine("");
      setSelectedRoleIds([]);
    } else {
      setUsername(target.username);
      setFullName(target.full_name);
      setPassword("");
      setLanguage(target.preferred_language);
      setProductionLine(target.production_line ?? "");
      setSelectedRoleIds(
        roles.filter((r) => target.roles.includes(r.role_name)).map((r) => r.id)
      );
    }
    setUsernameError(null);
    setFormError(null);
  }, [target, roles]);

  const operatorRole = roles.find((r) => r.role_name === ROLES.OPERATOR);
  const isOperatorSelected =
    operatorRole !== undefined && selectedRoleIds.includes(operatorRole.id);

  function toggleRole(roleId: number) {
    setSelectedRoleIds((prev) =>
      prev.includes(roleId) ? prev.filter((id) => id !== roleId) : [...prev, roleId]
    );
  }

  function handleClose() {
    setUsernameError(null);
    setFormError(null);
    onClose();
  }

  async function handleSubmit() {
    setUsernameError(null);
    setFormError(null);

    if (!username.trim() || !fullName.trim()) {
      setFormError(t("requiredFields"));
      return;
    }
    if (!isEdit && !password.trim()) {
      setFormError(t("passwordRequired"));
      return;
    }

    // A production line is only meaningful for operators.
    const line = isOperatorSelected && productionLine.trim() ? productionLine.trim() : null;

    setSaving(true);
    try {
      if (isEdit) {
        const user = target as User;
        await apiClient.patch(`/users/${user.id}`, {
          full_name: fullName,
          preferred_language: language,
          production_line: line,
        });
        await apiClient.post(`/users/${user.id}/roles`, { role_ids: selectedRoleIds });
      } else {
        await apiClient.post("/users", {
          username: username.trim(),
          full_name: fullName.trim(),
          password,
          preferred_language: language,
          production_line: line,
          role_ids: selectedRoleIds,
        });
      }
      onSuccess();
      handleClose();
    } catch (err) {
      if (getResponseStatus(err) === 409) {
        setUsernameError(t("usernameExists"));
      } else {
        setFormError(t("saveFailed"));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) handleClose(); }}>
      <DialogContent data-testid="user-form">
        <DialogHeader>
          <DialogTitle>{isEdit ? t("editUser") : t("createUser")}</DialogTitle>
          <DialogDescription>
            {isEdit ? t("editUserDescription") : t("createUserDescription")}
          </DialogDescription>
        </DialogHeader>

        {formError && (
          <Alert variant="destructive">
            <AlertDescription data-testid="user-form-error">{formError}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="username">{t("colUsername")}</Label>
            <Input
              id="username"
              value={username}
              disabled={isEdit}
              onChange={(e) => setUsername(e.target.value)}
              aria-invalid={usernameError !== null}
              data-testid="username-input"
            />
            {usernameError && (
              <p className="text-xs text-destructive" data-testid="username-error">
                {usernameError}
              </p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="fullName">{t("colFullName")}</Label>
            <Input
              id="fullName"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              data-testid="fullname-input"
            />
          </div>

          {!isEdit && (
            <div className="space-y-1">
              <Label htmlFor="password">{t("temporaryPassword")}</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                data-testid="password-input"
              />
            </div>
          )}

          <div className="space-y-1">
            <Label htmlFor="language">{t("language")}</Label>
            <Select value={language} onValueChange={setLanguage}>
              <SelectTrigger id="language" data-testid="language-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="en">English</SelectItem>
                <SelectItem value="es">Español</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1.5">
            <Label>{t("colRoles")}</Label>
            <div className="flex flex-wrap gap-2">
              {roles.map((role) => {
                const selected = selectedRoleIds.includes(role.id);
                return (
                  <Button
                    key={role.id}
                    type="button"
                    size="sm"
                    variant={selected ? "default" : "outline"}
                    aria-pressed={selected}
                    onClick={() => toggleRole(role.id)}
                    data-testid={`role-toggle-${role.role_name}`}
                  >
                    {roleLabel(role.role_name)}
                  </Button>
                );
              })}
            </div>
          </div>

          {/* FR-038: a production line only applies to machine operators. */}
          {isOperatorSelected && (
            <div className="space-y-1" data-testid="production-line-field">
              <Label htmlFor="productionLine">{t("colProductionLine")}</Label>
              <Input
                id="productionLine"
                value={productionLine}
                onChange={(e) => setProductionLine(e.target.value)}
                placeholder={t("productionLinePlaceholder")}
                data-testid="production-line-input"
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {tc("cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={saving} data-testid="save-user">
            {saving ? tc("saving") : tc("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

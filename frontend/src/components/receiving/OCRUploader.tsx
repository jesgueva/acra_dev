"use client";

import React, { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Upload, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/src/lib/api-client";

export interface OCRResult {
  supplier?: string;
  carrier?: string;
  bol_reference?: string;
  delivery_date?: string;
  items?: Array<{
    item_name: string;
    description?: string;
    quantity: number;
    pallets?: number;
    units_per_pallet?: number;
  }>;
  confidence: number;
}

interface OCRUploaderProps {
  onOCRResult: (result: OCRResult) => void;
}

export default function OCRUploader({ onOCRResult }: OCRUploaderProps) {
  const t = useTranslations("receiving");
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);

  async function processFile(file: File) {
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const { data } = await apiClient.post<OCRResult>("/deliveries/ocr", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      onOCRResult(data);
      toast.success(t("ocrSuccess"));
    } catch {
      toast.error(t("ocrError"));
    } finally {
      setUploading(false);
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) processFile(file);
    e.target.value = "";
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(true);
  }

  function handleDragLeave() {
    setDragging(false);
  }

  return (
    <div
      className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
        dragging ? "border-primary bg-primary/5" : "border-muted-foreground/30"
      }`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={() => !uploading && inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        id="ocr-file-input"
        type="file"
        accept="image/*,.pdf"
        className="sr-only"
        onChange={handleFileChange}
        aria-label={t("uploadFile")}
      />

      <div className="flex flex-col items-center gap-2 text-muted-foreground">
        {uploading ? (
          <>
            <Loader2 className="h-8 w-8 animate-spin" />
            <p className="text-sm">{t("uploading")}</p>
          </>
        ) : (
          <>
            <Upload className="h-8 w-8" />
            <p className="text-sm">{t("ocrDragDrop")}</p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                inputRef.current?.click();
              }}
            >
              {t("uploadFile")}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

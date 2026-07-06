"use client";

import React, { useRef, useState } from "react";
import Link from "next/link";
import { API_BASE_URL } from "@/lib/api";
import { useCompany } from "@/lib/CompanyContext";
import { useLanguage } from "@/lib/LanguageContext";

type ReadResult = {
  name: string;
  content: string;
  type: string;
  warnings?: string[];
  fields?: Record<string, unknown>;
};

const TEXT_EXTENSIONS = new Set([".txt", ".md", ".json", ".csv", ".xml", ".html", ".js", ".ts", ".tsx", ".css"]);

function extensionOf(name: string): string {
  const idx = name.lastIndexOf(".");
  return idx >= 0 ? name.slice(idx).toLowerCase() : "";
}

function isTextFile(file: File): boolean {
  return file.type.startsWith("text/") || TEXT_EXTENSIONS.has(extensionOf(file.name));
}

function readTextFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (event) => resolve(String(event.target?.result || ""));
    reader.onerror = () => reject(new Error("Read error"));
    reader.readAsText(file);
  });
}

function formatFields(fields?: Record<string, unknown>): string {
  if (!fields) return "";
  return Object.entries(fields)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join("\n");
}

export default function TeamPage() {
  const { t } = useLanguage();
  const { selectedCompanyId } = useCompany();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [isDragActive, setIsDragActive] = useState(false);
  const [isReading, setIsReading] = useState(false);
  const [isMatching, setIsMatching] = useState(false);
  const [readResults, setReadResults] = useState<ReadResult[]>([]);
  const [error, setError] = useState("");
  const [matchMessage, setMatchMessage] = useState("");

  const addFiles = (list: FileList | null) => {
    if (!list) return;
    setFiles((current) => [...current, ...Array.from(list)]);
    setError("");
    setMatchMessage("");
  };

  const removeFile = (index: number) => {
    setFiles((current) => current.filter((_, i) => i !== index));
  };

  const fallbackResult = async (file: File): Promise<ReadResult> => {
    if (isTextFile(file)) {
      return {
        name: file.name,
        type: file.type || "text/plain",
        content: await readTextFile(file),
      };
    }

    return {
      name: file.name,
      type: file.type || "binary",
      content: t("bankRecon.noOcrFallback"),
      warnings: ["ocr_backend_unavailable_or_not_configured"],
    };
  };

  const handleReadFiles = async () => {
    if (!files.length) {
      setError(t("team.noFilesToRead"));
      return;
    }

    setIsReading(true);
    setError("");
    setMatchMessage("");

    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/upload-documents`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`Backend unavailable: ${response.status}`);
      }

      const data = await response.json();
      const results: ReadResult[] = (data.results || []).map((item: any) => {
        if (item.status !== "analyzed") {
          return {
            name: item.filename || "document",
            type: "error",
            content: item.message || t("bankRecon.noOcrFallback"),
            warnings: ["analysis_failed"],
          };
        }

        const analysis = item.result || {};
        const fields = analysis.fields || {};
        const fieldText = formatFields(fields);
        const rawText = analysis.raw_text_preview || "";
        const warnings = Array.isArray(analysis.warnings) ? analysis.warnings : [];
        const content = [
          `Document class: ${analysis.document_class || "unknown"}`,
          fieldText,
          rawText ? `Extracted text:\n${rawText}` : "",
        ].filter(Boolean).join("\n\n");

        return {
          name: item.filename || analysis.source_file || "document",
          type: analysis.document_type || analysis.document_class || "document",
          content: content || t("bankRecon.noOcrFallback"),
          warnings,
          fields,
        };
      });

      setReadResults(results);
    } catch {
      const localResults = await Promise.all(files.map((file) => fallbackResult(file)));
      setReadResults(localResults);
      setError(t("bankRecon.noOcrFallback"));
    } finally {
      setIsReading(false);
    }
  };

  const handleMatchDocuments = async () => {
    if (!files.length) {
      setError(t("team.noFilesToRead"));
      return;
    }

    setIsMatching(true);
    setError("");
    setMatchMessage("");

    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    if (selectedCompanyId) formData.append("company_id", String(selectedCompanyId));

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/erp/match-documents`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(`Match failed: ${response.status}`);
      const data = await response.json();
      const count = Array.isArray(data.results) ? data.results.length : 0;
      setMatchMessage(`${t("team.matchAttach")}: ${count} document(s) processed.`);
    } catch {
      setError(t("team.matchError"));
    } finally {
      setIsMatching(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm text-amber-400/80">{t("home.subtitle")}</p>
          <h1 className="text-2xl font-bold text-white mt-1">{t("team.accountant")}</h1>
          <p className="text-sm text-gray-400 mt-2">{t("team.supportsMultiple")}</p>
        </div>
        <Link href="/bank-reconciliation" className="rounded-xl border border-amber-500/30 px-4 py-2 text-sm font-semibold text-amber-400 hover:bg-amber-500/10">
          {t("bankRecon.pageTitle")}
        </Link>
      </div>

      <section className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-4">
        <h2 className="text-lg font-semibold text-white">{t("team.attachDoc")}</h2>
        <div
          onDragOver={(event) => { event.preventDefault(); setIsDragActive(true); }}
          onDragLeave={() => setIsDragActive(false)}
          onDrop={(event) => { event.preventDefault(); setIsDragActive(false); addFiles(event.dataTransfer.files); }}
          onClick={() => fileInputRef.current?.click()}
          className={`cursor-pointer rounded-2xl border-2 border-dashed p-8 text-center transition-all ${isDragActive ? "border-amber-400 bg-amber-500/10" : "border-white/20 bg-black/20 hover:border-white/40"}`}
        >
          <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(event) => addFiles(event.target.files)} />
          <p className="text-white font-medium">{isDragActive ? t("team.dropFiles") : t("team.clickOrDrag")}</p>
          <p className="text-xs text-gray-500 mt-2">PDF, images, CSV, Excel and text files are accepted by the backend analyzer.</p>
        </div>

        {files.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-white">{t("team.attachedFiles")}</h3>
            {files.map((file, index) => (
              <div key={`${file.name}-${index}`} className="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                <div>
                  <p className="text-white">{file.name}</p>
                  <p className="text-xs text-gray-500">{file.type || "unknown"} · {(file.size / 1024).toFixed(1)} KB</p>
                </div>
                <button onClick={() => removeFile(index)} className="text-xs text-red-300 hover:text-red-200">Remove</button>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-3">
          <button disabled={!files.length || isReading} onClick={handleReadFiles} className="rounded-xl bg-amber-500 px-5 py-2.5 text-sm font-semibold text-black disabled:opacity-40">
            {isReading ? t("team.reading") : t("team.read")}
          </button>
          <button disabled={!files.length || isMatching} onClick={handleMatchDocuments} className="rounded-xl border border-emerald-500/30 px-5 py-2.5 text-sm font-semibold text-emerald-300 disabled:opacity-40 hover:bg-emerald-500/10">
            {isMatching ? t("team.matching") : t("team.matchAttach")}
          </button>
        </div>

        {error && <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">{error}</div>}
        {matchMessage && <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">{matchMessage}</div>}
      </section>

      {readResults.length > 0 && (
        <section className="rounded-2xl border border-white/10 bg-black/30 p-6 space-y-4">
          <h2 className="text-lg font-semibold text-white">{t("team.readContents")}</h2>
          {readResults.map((result, index) => (
            <article key={`${result.name}-${index}`} className="rounded-xl border border-white/10 bg-black/20 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-white">{result.name}</h3>
                  <p className="text-xs text-gray-500">{result.type}</p>
                </div>
                {result.warnings?.length ? <span className="rounded-lg border border-yellow-500/30 px-2 py-1 text-xs text-yellow-300">{result.warnings.join(", ")}</span> : null}
              </div>
              <pre className="mt-4 max-h-96 overflow-auto whitespace-pre-wrap rounded-xl bg-black/40 p-4 text-xs leading-relaxed text-gray-200">{result.content}</pre>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}

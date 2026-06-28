"use client";

import { useEffect } from "react";

const ACCEPTED_BANK_STATEMENT_ACCEPT = [
  ".csv",
  ".tsv",
  ".txt",
  ".xlsx",
  ".xls",
  ".xlsm",
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".webp",
  ".bmp",
  ".tif",
  ".tiff",
  ".ofx",
  ".qfx",
  ".qif",
  ".mt940",
  ".sta",
  "application/pdf",
  "image/*",
  "text/csv",
  "text/tab-separated-values",
  "text/plain",
  "application/vnd.ms-excel",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
].join(",");

const FORMAT_HINT =
  "Excel XLSX/XLS/XLSM · CSV/TSV/TXT · PDF · Images PNG/JPG/WEBP/TIFF/BMP · OFX/QIF · MT940";

export default function BankStatementUploadFormatEnhancer() {
  useEffect(() => {
    const applyAcceptedFormats = () => {
      document
        .querySelectorAll<HTMLInputElement>('input[type="file"]')
        .forEach((input) => {
          const currentAccept = input.getAttribute("accept") || "";
          const looksLikeBankStatementInput =
            currentAccept.includes(".csv") ||
            currentAccept.includes(".xls") ||
            input.name === "statement";

          if (looksLikeBankStatementInput) {
            input.setAttribute("accept", ACCEPTED_BANK_STATEMENT_ACCEPT);
          }
        });

      document.querySelectorAll<HTMLElement>("p,span").forEach((node) => {
        const text = (node.textContent || "").trim();
        if (text === "CSV · XLSX · XLS") {
          node.textContent = FORMAT_HINT;
        }
      });
    };

    applyAcceptedFormats();

    const observer = new MutationObserver(applyAcceptedFormats);
    observer.observe(document.body, { childList: true, subtree: true });

    return () => observer.disconnect();
  }, []);

  return null;
}

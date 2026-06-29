"use client";

import { useEffect } from "react";
import ReconciliationPageClient from "@/components/ReconciliationPageClient";

function replaceGoogleText(root: ParentNode) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) {
    const node = walker.currentNode as Text;
    if (node.nodeValue && /Google/i.test(node.nodeValue)) nodes.push(node);
  }
  nodes.forEach((node) => {
    node.nodeValue = (node.nodeValue || "")
      .replace(/بيانات Google/g, "بيانات الدفاتر في النظام المحاسبي")
      .replace(/Google only/g, "Books only")
      .replace(/Google فقط/g, "الدفاتر فقط")
      .replace(/Google/g, "الدفاتر");
  });
}

export default function ReconciliationPageNoGoogle() {
  useEffect(() => {
    replaceGoogleText(document.body);
    const observer = new MutationObserver(() => replaceGoogleText(document.body));
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, []);

  return <ReconciliationPageClient />;
}

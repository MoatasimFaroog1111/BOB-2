import { describe, expect, it } from "vitest";

import { escapeHtml } from "./escapeHtml";

describe("escapeHtml", () => {
  it("escapes text before interpolation into generated print markup", () => {
    const malicious = `<img src=x onerror="alert('xss')"> & journal`;
    const escaped = escapeHtml(malicious);

    expect(escaped).toBe(
      "&lt;img src=x onerror=&quot;alert(&#39;xss&#39;)&quot;&gt; &amp; journal",
    );
    expect(escaped).not.toContain("<img");
    expect(escaped).not.toContain('onerror="');
  });

  it("handles nullish and numeric values without producing unsafe markup", () => {
    expect(escapeHtml(null)).toBe("");
    expect(escapeHtml(undefined)).toBe("");
    expect(escapeHtml(1234)).toBe("1234");
  });
});

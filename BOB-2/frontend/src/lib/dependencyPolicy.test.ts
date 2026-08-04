import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

type PackageManifest = {
  dependencies?: Record<string, string>;
};

const prereleaseTag = /(?:alpha|beta|canary|preview|rc)/i;

describe("production dependency policy", () => {
  it("does not ship prerelease runtime packages", () => {
    const manifest = JSON.parse(
      readFileSync(new URL("../../package.json", import.meta.url), "utf8"),
    ) as PackageManifest;
    const offenders = Object.entries(manifest.dependencies ?? {}).filter(([, version]) =>
      prereleaseTag.test(version),
    );

    expect(offenders).toEqual([]);
  });
});

"""Replace deprecated datetime.utcnow while preserving UTC-naive DB semantics."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (ROOT / "app", ROOT / "tests")
REPLACEMENT = "datetime.now(timezone.utc).replace(tzinfo=None)"


def ensure_timezone_import(content: str) -> str:
    single = re.compile(r"^from datetime import ([^\n(]+)$", re.MULTILINE)
    match = single.search(content)
    if match:
        names = [part.strip() for part in match.group(1).split(",")]
        if "timezone" not in names:
            names.append("timezone")
        replacement = "from datetime import " + ", ".join(names)
        return content[: match.start()] + replacement + content[match.end() :]

    multiline = re.compile(
        r"^from datetime import \((?P<body>.*?)^\)",
        re.MULTILINE | re.DOTALL,
    )
    match = multiline.search(content)
    if match:
        body = match.group("body")
        imported = {
            item.strip()
            for item in body.replace("\n", "").split(",")
            if item.strip()
        }
        if "timezone" in imported:
            return content
        replacement = "from datetime import (" + body + "    timezone,\n)"
        return content[: match.start()] + replacement + content[match.end() :]

    raise RuntimeError("datetime.utcnow usage without supported datetime import")


def migrate(path: Path) -> bool:
    content = path.read_text(encoding="utf-8")
    if "datetime.utcnow" not in content:
        return False
    content = ensure_timezone_import(content)
    content = content.replace("datetime.utcnow()", REPLACEMENT)
    content = content.replace(
        "default=datetime.utcnow",
        f"default=lambda: {REPLACEMENT}",
    )
    if "datetime.utcnow" in content:
        raise RuntimeError(f"Unmigrated datetime.utcnow reference in {path}")
    path.write_text(content, encoding="utf-8")
    return True


def main() -> None:
    changed = []
    for root in TARGETS:
        for path in sorted(root.rglob("*.py")):
            if migrate(path):
                changed.append(str(path.relative_to(ROOT)))
    for root in TARGETS:
        remaining = [
            str(path.relative_to(ROOT))
            for path in root.rglob("*.py")
            if "datetime.utcnow" in path.read_text(encoding="utf-8")
        ]
        if remaining:
            raise RuntimeError(f"datetime.utcnow remains: {remaining}")
    print("utcnow-migration-files=" + ",".join(changed))


if __name__ == "__main__":
    main()

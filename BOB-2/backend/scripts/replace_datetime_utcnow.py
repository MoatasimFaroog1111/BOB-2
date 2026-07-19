"""Replace deprecated datetime.utcnow while preserving UTC-naive DB semantics."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (ROOT / "app", ROOT / "tests")
REPLACEMENT = "datetime.now(timezone.utc).replace(tzinfo=None)"


def ensure_timezone_import(content: str) -> str:
    if "from datetime import timezone" in content:
        return content

    future_line = "from __future__ import annotations\n"
    if future_line in content:
        return content.replace(
            future_line,
            future_line + "\nfrom datetime import timezone\n",
            1,
        )

    # A second import from the same module is valid and avoids rewriting
    # parenthesized or aliased import statements.
    if content.startswith(('"""', "'''")):
        quote = content[:3]
        closing = content.find(quote, 3)
        if closing >= 0:
            insertion = closing + 3
            return (
                content[:insertion]
                + "\n\nfrom datetime import timezone"
                + content[insertion:]
            )
    return "from datetime import timezone\n\n" + content


def migrate(path: Path) -> bool:
    content = path.read_text(encoding="utf-8").lstrip("\\ufeff")
    if "datetime.utcnow" not in content:
        return False
    content = ensure_timezone_import(content)
    content = content.replace("datetime.utcnow()", REPLACEMENT)
    content = content.replace(
        "default=datetime.utcnow",
        f"default=lambda: {REPLACEMENT}",
    )
    content = content.replace(
        "onupdate=datetime.utcnow",
        f"onupdate=lambda: {REPLACEMENT}",
    )
    if "datetime.utcnow" in content:
        raise RuntimeError(f"Unmigrated datetime.utcnow reference in {path}")
    compile(content, str(path), "exec")
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

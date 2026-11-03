#!/usr/bin/env python3
"""
Build Iter Browser HTML from the current source tree.

The HTML/browser runtime remains the template. Only embedded Python source is
refreshed from the local filesystem:

    ./iter.py
    ./shell.py
    ./tools/*.py
    ./channels/*.py
    ./transformations/*.py

Runtime path mapping is direct:
    /work/iter/iter.py                 <- ./iter.py
    /work/iter/tools/send.py           <- ./tools/send.py
    /work/iter/channels/terminal.py    <- ./channels/terminal.py
    /work/iter/transformations/foo.py  <- ./transformations/foo.py

It also refreshes the template's Python migration/repair literals from those
same files, so an old repair cannot silently reinstall stale Python code.

Usage:
    python3 build_iter_browser.py

Defaults:
    template: Iter Browser.template.html if present, otherwise Iter Browser.html
    output:   Iter Browser.generated.html
    source:   current directory

Or:
    python3 build_iter_browser.py --template "Iter Browser.html" \
        --output "Iter Browser.generated.html" --source-root .
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


RUNTIME_ROOT = "/work/iter/"

# These are Python-source compatibility/repair literals in the current HTML.
# They must come from the same local files as the normal seeds.
PYTHON_LITERAL_SOURCES = {
    "NEW_STOCK_SEND": "tools/send.py",
    "NEW_STOCK_SCREENSHOT": "tools/screenshot.py",
    "NEW_STOCK_TERMINAL": "channels/terminal.py",
    "PYTHON_TOOL_RESTORE_V9_SOURCE": "tools/python.py",
    "NEW_WEBSEARCH_TOOL": "tools/websearch.py",
}


def js_string(value: str) -> str:
    """JSON/JavaScript string literal safe inside an HTML <script> element."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def source_path_for_runtime(runtime_path: str, source_root: Path) -> Path:
    if not runtime_path.startswith(RUNTIME_ROOT):
        raise ValueError(f"not an Iter runtime path: {runtime_path}")
    rel = runtime_path[len(RUNTIME_ROOT):]
    return source_root / rel


def decode_js_path_literal(literal: str) -> str:
    # Paths in this template contain no escape-sensitive single-quoted data.
    if literal.startswith('"'):
        return json.loads(literal)
    if literal.startswith("'"):
        body = literal[1:-1]
        return (
            body.replace("\\'", "'")
            .replace("\\\\", "\\")
        )
    raise ValueError(f"unsupported JS path literal: {literal[:20]!r}")


SEED_RE = re.compile(
    r"""
    seed\(
        \s*
        (?P<path>
            "(?:\\.|[^"\\])*"
            |
            '(?:\\.|[^'\\])*'
        )
        \s*,\s*
        (?P<source>"(?:\\.|[^"\\])*")
        \s*
    \);
    """,
    re.VERBOSE,
)


def refresh_python_seeds(html: str, source_root: Path) -> tuple[str, list[str]]:
    replaced: list[str] = []
    missing: list[tuple[str, Path]] = []

    pieces: list[str] = []
    last = 0

    for match in SEED_RE.finditer(html):
        runtime_path = decode_js_path_literal(match.group("path"))
        if not runtime_path.endswith(".py"):
            continue
        if not runtime_path.startswith(RUNTIME_ROOT):
            continue

        local_path = source_path_for_runtime(runtime_path, source_root)
        if not local_path.is_file():
            missing.append((runtime_path, local_path))
            continue

        source = local_path.read_text(encoding="utf-8")
        replacement = (
            "seed("
            + match.group("path")
            + ", "
            + js_string(source)
            + ");"
        )

        pieces.append(html[last:match.start()])
        pieces.append(replacement)
        last = match.end()
        replaced.append(runtime_path)

    if missing:
        details = "\n".join(
            f"  {runtime} <- {local}"
            for runtime, local in missing
        )
        raise FileNotFoundError(
            "Template embeds Python files that are missing from the source tree:\n"
            + details
        )

    pieces.append(html[last:])
    return "".join(pieces), replaced


def replace_const_string(html: str, name: str, source: str) -> tuple[str, bool]:
    # Match only a simple const NAME = "..." source literal.
    pattern = re.compile(
        r"(?P<prefix>\bconst\s+"
        + re.escape(name)
        + r"\s*=\s*)"
        r'(?P<value>"(?:\\.|[^"\\])*")'
        r"(?P<suffix>\s*;)"
    )
    matches = list(pattern.finditer(html))
    if not matches:
        return html, False
    if len(matches) != 1:
        raise RuntimeError(f"{name}: expected one source literal, found {len(matches)}")

    match = matches[0]
    replacement = (
        match.group("prefix")
        + js_string(source)
        + match.group("suffix")
    )
    return html[:match.start()] + replacement + html[match.end():], True


def refresh_python_literals(html: str, source_root: Path) -> tuple[str, list[str]]:
    refreshed: list[str] = []
    for const_name, rel in PYTHON_LITERAL_SOURCES.items():
        # Only require a local file when this HTML actually contains the literal.
        if not re.search(r"\bconst\s+" + re.escape(const_name) + r"\s*=", html):
            continue

        local_path = source_root / rel
        if not local_path.is_file():
            raise FileNotFoundError(
                f"{const_name} is present in the template but its source file is missing: "
                f"{local_path}"
            )

        source = local_path.read_text(encoding="utf-8")
        html, changed = replace_const_string(html, const_name, source)
        if changed:
            refreshed.append(f"{const_name} <- {rel}")
    return html, refreshed


def default_template() -> Path:
    preferred = Path("Iter Browser.template.html")
    if preferred.is_file():
        return preferred
    return Path("Iter Browser.html")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help='HTML template (default: "Iter Browser.template.html", else "Iter Browser.html")',
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("Iter Browser.generated.html"),
        help='generated HTML (default: "Iter Browser.generated.html")',
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("."),
        help="root containing iter.py, tools/, channels/, transformations/ (default: .)",
    )
    args = parser.parse_args()

    template = args.template or default_template()
    source_root = args.source_root.resolve()
    output = args.output

    if not template.is_file():
        parser.error(f"template not found: {template}")

    required_iter = source_root / "iter.py"
    if not required_iter.is_file():
        parser.error(f"source tree must contain {required_iter}")

    html = template.read_text(encoding="utf-8")
    original = html

    html, seeds = refresh_python_seeds(html, source_root)
    html, literals = refresh_python_literals(html, source_root)

    if not seeds:
        raise RuntimeError("No /work/iter/*.py seed calls found in template")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

    print(f"template: {template}")
    print(f"source:   {source_root}")
    print(f"output:   {output}")
    print(f"python seed occurrences refreshed: {len(seeds)}")
    print(f"python repair/migration literals refreshed: {len(literals)}")
    print(f"browser/UI bytes otherwise preserved: {'yes' if html != original else 'no changes'}")

    # Report duplicate seed paths because the current HTML intentionally contains
    # a few compatibility seeds. Every occurrence is refreshed from one source file.
    counts: dict[str, int] = {}
    for path in seeds:
        counts[path] = counts.get(path, 0) + 1
    duplicates = {p: n for p, n in counts.items() if n > 1}
    if duplicates:
        print("duplicate Python seed occurrences refreshed consistently:")
        for path, count in sorted(duplicates.items()):
            print(f"  {count}x {path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

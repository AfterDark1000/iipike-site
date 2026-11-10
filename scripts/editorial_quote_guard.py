"""Protect editor intake from repeated stray Markdown quote markers.

This is a narrow, read-only preflight planner. It never changes a story
directly. The GitHub intake validation workflow checks fresh blob SHAs before
applying the proposed whitespace-only changes to editorial-intake.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from scripts.site_rich_text import markdown_to_blocks

STORY = re.compile(r"editorial_inbox/stories/([a-z0-9]+(?:-[a-z0-9]+)*)\.json\Z")
EMPTY = re.compile(r"[ \t]*>[ \t]*\Z")
QUOTED = re.compile(r"[ \t]*> [^\s].*\Z")


def normalize_empty_quote_markers(source):
    """Remove *only* a stand-alone > between two nonempty quote lines.

    Handles '>' and '> ' (including tabs/spaces). Does not rewrite text,
    quotes, attribution, links, or deliberately blank lines elsewhere.
    Returns (text, original 1-based line numbers).
    """
    if not isinstance(source, str):
        raise TypeError("Markdown must be text")
    lines = source.split("\n")
    removed = []
    output = []
    for i, line in enumerate(lines):
        if (EMPTY.fullmatch(line)
                and 0 < i < len(lines) - 1
                and QUOTED.fullmatch(lines[i - 1])
                and QUOTED.fullmatch(lines[i + 1])):
            removed.append(i + 1)
            continue
        output.append(line)
    return "\n".join(output), tuple(removed)


def _git(*args):
    proc = subprocess.run(
        ["git", *args], check=True, text=True, capture_output=True,
        encoding="utf-8", timeout=30,
    )
    return proc.stdout


def collect_repairs(ref="origin/editorial-intake", main_ref="origin/main"):
    """Collect only unpublished, approved and fully valid repaired stories.

    No network or writes: the caller must fetch refs first. A workflow can
    safely compare hashes with the freshest Contents API data before writing.
    """
    records = json.loads(_git("show", f"{main_ref}:news.json"))
    published = {r.get("id") for r in records if isinstance(r, dict)}
    paths = _git("ls-tree", "-r", "--name-only", ref, "--",
                 "editorial_inbox/stories").splitlines()
    plans = []
    for path in paths:
        matched = STORY.fullmatch(path)
        if not matched or matched.group(1) in published:
            continue
        blob = _git("show", f"{ref}:{path}")
        data = json.loads(blob)
        if (not isinstance(data, dict) or data.get("id") != matched.group(1)
                or data.get("status") != "editor_approved"
                or data.get("approved_by") != "human_editor"):
            continue
        source = data.get("article_markdown")
        if not isinstance(source, str):
            continue
        repaired, removed = normalize_empty_quote_markers(source)
        if not removed:
            continue
        try:
            markdown_to_blocks(repaired)
        except (ValueError, TypeError) as exc:
            # There is another error: do not silently rewrite an invalid story.
            print(f"QUOTE_GUARD_NEEDS_EDITOR: {matched.group(1)}: {exc}")
            continue
        plans.append({
            "path": path,
            "id": matched.group(1),
            "original_markdown_sha256": hashlib.sha256(
                source.encode("utf-8")).hexdigest(),
            "repaired_markdown": repaired,
            "removed_lines": list(removed),
        })
    return plans


def main():
    parser = argparse.ArgumentParser(description="Read-only quote repair plan")
    parser.add_argument("--ref", default="origin/editorial-intake")
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plans = collect_repairs(args.ref, args.main_ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"fixes": plans}, ensure_ascii=False),
                           encoding="utf-8")
    for item in plans:
        print(f"QUOTE_GUARD_FIXABLE: {item['id']} lines {item['removed_lines']}")
    print(f"QUOTE_GUARD_PLAN: {len(plans)} safe, unpublished Markdown fixes")
    print("READ_ONLY: no stories were changed by the preflight planner.")


if __name__ == "__main__":
    main()

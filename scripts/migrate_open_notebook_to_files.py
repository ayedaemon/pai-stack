#!/usr/bin/env python3
"""
migrate_open_notebook_to_files.py

Exports all notebooks, notes, and sources from a running Open Notebook API
instance (default: http://localhost:5055) into a clean, human-readable
Markdown file structure.

Structure:
  <output_dir>/<notebook_name>/
    ├── notebook.json
    ├── notes/
    │   └── YYYY-MM-DD-<slug>.md
    └── sources/
        └── YYYY-MM-DD-<slug>.md
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path


def slugify(text: str) -> str:
    """Convert text into a clean filesystem slug."""
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:60] or "untitled"


def extract_symbol_anchors(content: str) -> list[str]:
    """Find all @symbol:... references in markdown text."""
    if not content:
        return []
    return sorted(list(set(re.findall(r"@symbol:[^\s\)\`\"\']+", content))))


def api_get(base_url: str, endpoint: str):
    """Execute GET request against the Open Notebook API."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    req = urllib.request.Request(url, headers={"User-Agent": "pai-migration/1.0"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Migrate Open Notebook data to Markdown files.")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("OPEN_NOTEBOOK_URL", "http://localhost:5055"),
        help="Open Notebook API base URL",
    )
    parser.add_argument(
        "--output-dir",
        default=os.environ.get(
            "RESEARCH_DIR",
            str(Path(os.environ.get("WORKSPACE_DIR", "/Users/rishabh.umrao/Personal")) / "research"),
        ),
        help="Target directory for research vault",
    )
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to Open Notebook API at {api_url}...")
    try:
        notebooks = api_get(api_url, "/api/notebooks")
    except Exception as e:
        print(f"Error connecting to Open Notebook API: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(notebooks)} notebooks. Target vault: {out_dir}\n")

    total_notes_exported = 0
    total_sources_exported = 0

    # Cache all sources
    all_sources = api_get(api_url, "/api/sources")
    sources_by_nb: dict[str, list] = {}
    for s_summary in all_sources:
        try:
            s_detail = api_get(api_url, f"/api/sources/{s_summary['id']}")
            for nb_id in s_detail.get("notebooks", []):
                sources_by_nb.setdefault(nb_id, []).append(s_detail)
        except Exception as e:
            print(f"Warning: Failed to fetch source {s_summary['id']}: {e}")

    for nb in notebooks:
        nb_id = nb["id"]
        nb_name = nb.get("name", "unnamed")
        nb_dir = out_dir / nb_name
        notes_dir = nb_dir / "notes"
        sources_dir = nb_dir / "sources"
        notes_dir.mkdir(parents=True, exist_ok=True)
        sources_dir.mkdir(parents=True, exist_ok=True)

        # 1. Save notebook.json metadata
        nb_meta = {
            "id": nb_id,
            "name": nb_name,
            "description": nb.get("description", ""),
            "created": nb.get("created"),
            "updated": nb.get("updated"),
            "archived": nb.get("archived", False),
        }
        (nb_dir / "notebook.json").write_text(json.dumps(nb_meta, indent=2))

        # 2. Export notes
        nb_notes = api_get(api_url, f"/api/notes?notebook_id={nb_id}")
        print(f"[{nb_name}] Exporting {len(nb_notes)} notes...")

        for n_summary in nb_notes:
            note_id = n_summary["id"]
            try:
                note = api_get(api_url, f"/api/notes/{note_id}")
            except Exception as e:
                print(f"  Warning: Failed to fetch note {note_id}: {e}")
                continue

            title = note.get("title") or "Untitled Note"
            content = note.get("content") or ""
            created_raw = note.get("created") or ""
            updated_raw = note.get("updated") or ""
            created_date = created_raw.split(" ")[0] if " " in created_raw else "2026-09-20"
            slug = slugify(title)
            filename = f"{created_date}-{slug}.md"

            anchors = extract_symbol_anchors(content)

            # Build YAML frontmatter
            frontmatter_lines = [
                "---",
                f'id: "{note_id}"',
                f'title: {json.dumps(title)}',
                f'notebook: "{nb_name}"',
                f'notebook_id: "{nb_id}"',
                f'note_type: "{note.get("note_type", "human")}"',
                f'created: "{created_raw}"',
                f'updated: "{updated_raw}"',
            ]
            if anchors:
                frontmatter_lines.append("anchors:")
                for a in anchors:
                    frontmatter_lines.append(f'  - "{a}"')
            frontmatter_lines.append("---\n")

            full_doc = "\n".join(frontmatter_lines) + f"\n# {title}\n\n" + content.strip() + "\n"
            (notes_dir / filename).write_text(full_doc, encoding="utf-8")
            total_notes_exported += 1

        # 3. Export sources
        nb_sources = sources_by_nb.get(nb_id, [])
        print(f"[{nb_name}] Exporting {len(nb_sources)} sources...")

        for source in nb_sources:
            source_id = source["id"]
            s_title = source.get("title") or "Untitled Source"
            s_url = source.get("asset", {}).get("url") or ""
            s_file = source.get("asset", {}).get("file_path") or ""
            s_text = source.get("full_text") or ""
            s_created = source.get("created") or ""
            s_updated = source.get("updated") or ""
            s_date = s_created.split(" ")[0] if " " in s_created else "2026-09-20"
            s_slug = slugify(s_title)
            s_filename = f"{s_date}-{s_slug}.md"

            frontmatter_lines = [
                "---",
                f'id: "{source_id}"',
                f'title: {json.dumps(s_title)}',
                f'notebook: "{nb_name}"',
                f'notebook_id: "{nb_id}"',
                f'url: "{s_url}"',
                f'file_path: "{s_file}"',
                f'created: "{s_created}"',
                f'updated: "{s_updated}"',
                "---\n",
            ]

            full_doc = "\n".join(frontmatter_lines) + f"\n# {s_title}\n\n"
            if s_url:
                full_doc += f"**Source URL**: [{s_url}]({s_url})\n\n"
            full_doc += s_text.strip() + "\n"

            (sources_dir / s_filename).write_text(full_doc, encoding="utf-8")
            total_sources_exported += 1

        print(f"[{nb_name}] Done.\n")

    print(
        f"=== Migration Complete ===\n"
        f"Vault Location: {out_dir}\n"
        f"Notebooks: {len(notebooks)}\n"
        f"Notes Exported: {total_notes_exported}\n"
        f"Sources Exported: {total_sources_exported}\n"
    )


if __name__ == "__main__":
    main()

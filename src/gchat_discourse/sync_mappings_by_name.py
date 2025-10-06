"""Update `mappings` in config.yaml by matching Google Chat spaces to
Discourse categories purely by name.

For each Google Chat space, if a Discourse category exists with the same
display name (case-insensitive, trimmed), create or update a mapping
entry {google_space_id, discourse_category_id} in the `mappings` list in
the config file. Existing mappings for spaces that are unchanged are left
alone. The file is backed up to config.yaml.bak and a unified diff is
presented for confirmation before overwrite.

Usage:
    python -m gchat_discourse.sync_mappings_by_name
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional

from gchat_discourse.config_loader import Config
from gchat_discourse.discourse_client import DiscourseClient, Category
from gchat_discourse.google_chat_client import GoogleChatClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _normalize(name: Optional[str]) -> str:
    return (name or "").strip().lower()


def main(config_path: str = "config.yaml", debug_responses: bool = False) -> None:
    if debug_responses:
        import logging as _logging

        _logging.getLogger().setLevel(_logging.DEBUG)
    cfg = Config(config_path)

    dc = DiscourseClient(
        url=cfg.discourse_url,
        api_key=cfg.discourse_api_key,
        api_username=cfg.discourse_username,
    )

    print("Validating Discourse API credentials...")
    if not dc.validate_api_key():
        print("Failed to validate Discourse credentials. Aborting.")
        return

    gc = GoogleChatClient(
        credentials_file=cfg.google_credentials_file,
        token_file=cfg.google_token_file,
    )

    # Fetch Discourse categories
    print("Fetching Discourse categories...")
    raw = dc._make_request("GET", "/categories.json") or {}
    category_tree = raw.get("category_list", {}).get("categories", [])
    children = raw.get("category_list", {}).get("children")

    categories: List[Category]
    if children:
        def walk(node: Dict[str, Any], out: List[Category]):
            out.append(Category.from_dict(node))
            for c in node.get("children", []):
                walk(c, out)

        out: List[Category] = []
        for root in children:
            walk(root, out)
        categories = out
    else:
        categories = [Category.from_dict(c) for c in category_tree]

    name_to_category = { _normalize(c.name): c for c in categories if c.name }

    print("Fetching Google Chat spaces (may prompt for auth)...")
    spaces = gc.list_spaces()
    if not spaces:
        print("No spaces returned or failed to list spaces.")
        return

    # Start with existing mappings preserved unless replaced
    new_mappings: List[Dict[str, Any]] = [m.copy() for m in (cfg.space_mappings or [])]
    # Map space id -> mapping index in new_mappings for quick update
    idx_by_space = { m.get("google_space_id"): i for i, m in enumerate(new_mappings) }

    added = 0
    updated = 0
    unchanged = 0
    skipped = 0

    for s in spaces:
        sid = s.get("name") or s.get("spaceId") or s.get("space_id")
        if sid is None:
            continue
        sid = str(sid)
        display_raw = s.get("displayName") or s.get("name")
        if not display_raw or display_raw.startswith("spaces/"):
            print(f"Skipping space id={sid} because it has no displayName/name (likely inaccessible)")
            continue
        display = display_raw
        norm = _normalize(display)

        if norm not in name_to_category:
            skipped += 1
            print(f"No matching category for space '{display}', skipping")
            continue

        cat = name_to_category[norm]

        existing = cfg.get_mapping_for_space(sid)
        if existing:
            if existing.get("discourse_category_id") == cat.id:
                unchanged += 1
                print(f"Mapping for '{display}' already correct (id={cat.id})")
                continue
            # update existing mapping
            i = idx_by_space.get(sid)
            if i is not None:
                new_mappings[i]["discourse_category_id"] = cat.id
                updated += 1
                print(f"Updated mapping for '{display}' -> category id={cat.id}")
            else:
                # should not happen, but handle defensively
                new_mappings.append({"google_space_id": sid, "discourse_category_id": cat.id})
                added += 1
                print(f"Added mapping for '{display}' -> category id={cat.id}")
        else:
            new_mappings.append({"google_space_id": sid, "discourse_category_id": cat.id})
            added += 1
            print(f"Added mapping for '{display}' -> category id={cat.id}")

    print("\nSummary:")
    print(f"  Added: {added}")
    print(f"  Updated: {updated}")
    print(f"  Unchanged: {unchanged}")
    print(f"  Skipped (no matching category): {skipped}")

    if new_mappings != (cfg.space_mappings or []):
        # Write changes with same pattern as manage_mappings
        try:
            import os
            import shutil
            import yaml
            import difflib

            backup_path = cfg.config_path + ".bak"
            if os.path.exists(cfg.config_path):
                shutil.copy2(cfg.config_path, backup_path)
                print(f"Backed up existing config to {backup_path}")

            with open(cfg.config_path, "r") as f:
                raw = yaml.safe_load(f) or {}

            new_raw = dict(raw)
            new_raw["mappings"] = new_mappings

            old_str = yaml.safe_dump(raw, sort_keys=False)
            new_str = yaml.safe_dump(new_raw, sort_keys=False)

            diff = list(difflib.unified_diff(
                old_str.splitlines(keepends=True),
                new_str.splitlines(keepends=True),
                fromfile=cfg.config_path,
                tofile=cfg.config_path + ".new",
            ))

            if diff:
                print("\nConfig changes:\n")
                for line in diff:
                    print(line, end="")

            apply_changes = (
                input("Apply these changes to your config file? [y/N]: ")
                .strip()
                .lower()
                == "y"
            )

            if not apply_changes:
                new_path = cfg.config_path + ".new"
                with open(new_path, "w") as f:
                    f.write(new_str)
                print(f"Aborted. New config written to {new_path}. Backup is at {backup_path}")
            else:
                with open(cfg.config_path, "w") as f:
                    yaml.safe_dump(new_raw, f)
                print("Mappings updated in config file.")

        except Exception as e:
            print(f"Failed to update config file: {e}")
    else:
        print("No changes to mappings needed.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync mappings by name between Google Chat and Discourse")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--debug-responses",
        action="store_true",
        help="Enable debug-level logging to print full Discourse response payloads",
    )
    args = parser.parse_args()

    try:
        main(config_path=args.config, debug_responses=args.debug_responses)
    except KeyboardInterrupt:
        pass

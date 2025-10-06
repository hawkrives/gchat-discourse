"""Interactive mapping tool: list Discourse categories and Google Chat spaces,
allow organizing categories into a hierarchy, map spaces to categories, and
create categories on demand. Persists mappings to config.yaml.

Usage: run this module with the project's Python environment, e.g.:
    python -m gchat_discourse.manage_mappings
"""

from __future__ import annotations

# stdlib
import logging
from typing import Dict, Any, List, Optional

from gchat_discourse.config_loader import Config
from gchat_discourse.discourse_client import DiscourseClient, Category
from gchat_discourse.google_chat_client import GoogleChatClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def choose(
    prompt: str,
    choices: List[str],
    allow_none: bool = False,
    zero_label: Optional[str] = None,
) -> Optional[int]:
    """Show numbered choices and return selected index or None.

    zero_label: optional string to display for the 0 option (e.g. "None / skip" or
    "Create a new category"). If provided and allow_none is True, pressing 0 will
    return None.
    """
    for i, c in enumerate(choices, start=1):
        print(f"{i}) {c}")

    if allow_none:
        label = zero_label or "None / skip"
        print(f"0) {label}")

    while True:
        sel = input(prompt).strip()
        if allow_none and sel == "0":
            return None
        try:
            idx = int(sel)
            if 1 <= idx <= len(choices):
                return idx - 1
        except ValueError:
            pass
        print("Invalid selection, try again.")


def display_categories(categories: List[Category]) -> None:
    print("\nDiscourse categories:\n")
    for c in categories:
        pid = c.parent_category_id or "(root)"
        print(f"- id={c.id} name={c.name} parent={pid}")


def flatten_category_tree(categories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def walk(node: Dict[str, Any], depth: int = 0):
        out.append(
            {
                "id": node.get("id"),
                "name": ("  " * depth) + node.get("name", ""),
                "raw": node,
            }
        )
        for child in node.get("children", []):
            walk(child, depth + 1)

    for root in categories:
        walk(root, 0)

    return out


def main(config_path: str = "config.yaml") -> None:
    cfg = Config(config_path)

    # Init clients
    dc = DiscourseClient(
        url=cfg.discourse_url,
        api_key=cfg.discourse_api_key,
        api_username=cfg.discourse_username,
    )
    # Validate Discourse credentials at startup to fail fast if misconfigured
    print("Validating Discourse API credentials...")
    if not dc.validate_api_key():
        print(
            "Failed to validate Discourse credentials."
            "Please check 'discourse.url', 'discourse.api_key', and 'discourse.api_username' in your config."
        )
        return
    gc = GoogleChatClient(
        credentials_file=cfg.google_credentials_file,
        token_file=cfg.google_token_file,
    )

    # Fetch current categories and spaces
    print("Fetching Discourse categories...")
    raw = dc._make_request("GET", "/categories.json") or {}
    category_tree = raw.get("category_list", {}).get("categories", [])

    # The categories endpoint returns a flat list and a category_tree; try to use tree if available
    # Attempt to use a nested children tree if present, otherwise use flat categories
    children = raw.get("category_list", {}).get("children")
    if children:
        flat = flatten_category_tree(children)
        categories = [Category.from_dict(item["raw"]) for item in flat]
    else:
        categories = [Category.from_dict(c) for c in category_tree]

    display_categories(categories)

    print("\nFetching Google Chat spaces (you may be prompted to authenticate)...")
    spaces = gc.list_spaces()
    # (no separate human-readable list needed)

    if not spaces:
        print("No spaces available or failed to list spaces.")
        return

    # Let user map each space to a category
    new_mappings: List[Dict[str, Any]] = (
        cfg.space_mappings.copy() if cfg.space_mappings else []
    )

    for s in spaces:
        # Prefer the canonical 'name' (full resource name like 'spaces/AAA'), fall back to spaceId
        sid = s.get("name") or s.get("spaceId") or s.get("space_id")
        if sid is None:
            # Skip spaces without an identifier
            continue
        sid = str(sid)
        display_name = s.get("displayName") or s.get("name") or sid

        existing = cfg.get_mapping_for_space(str(sid))
        if existing:
            print(
                f"Space {display_name} already mapped to category {existing.get('discourse_category_id')}, skipping."
            )
            continue

        print(f"\nSpace: {display_name} id={sid}")

        cat_choices = [f"{c.id}: {c.name}" for c in categories]
        # Allow 0 to create a new category for this space; provide an explicit
        # label so it's not confused with the generic "None / skip" text.
        cat_idx = choose(
            "Select category number to map this space (or 0 to create new): ",
            cat_choices,
            allow_none=True,
            zero_label="Create a new category",
        )

        if cat_idx is None:
            # Create a new category now
            name = input("New category name: ").strip()
            parent = input("Parent category id (leave empty for root): ").strip()
            parent_id = int(parent) if parent else None
            resp = dc.create_category(name=name, parent_category_id=parent_id)
            if resp and resp.category:
                print(
                    f"Created category: id={resp.category.id} name={resp.category.name}"
                )
                categories.append(resp.category)
                chosen = resp.category
            else:
                print("Failed to create category, skipping mapping for this space.")
                continue
        else:
            if cat_idx < 0 or cat_idx >= len(cat_choices):
                print("Invalid category choice, skipping.")
                continue

            chosen = categories[cat_idx]

        # Confirm mapping
        yn = (
            input(f"Map space '{display_name}' -> category '{chosen.name}'? [y/N]: ")
            .strip()
            .lower()
        )
        if yn != "y":
            print("Skipping mapping.")
            continue

        mapping = {
            "google_space_id": sid,
            "discourse_category_id": chosen.id,
        }
        new_mappings.append(mapping)
        print(f"Mapped {display_name} -> {chosen.name} (id={chosen.id})")

    # Offer to create categories
    while True:
        c = (
            input("Do you want to create a new Discourse category? [y/N]: ")
            .strip()
            .lower()
        )
        if c != "y":
            break

        name = input("Category name: ").strip()
        parent = input("Parent category id (leave empty for root): ").strip()
        parent_id = int(parent) if parent else None

        resp = dc.create_category(name=name, parent_category_id=parent_id)
        if resp and resp.category:
            print(f"Created category: id={resp.category.id} name={resp.category.name}")
            categories.append(resp.category)
        else:
            print("Failed to create category")

    # Persist mappings back to config.yaml
    if new_mappings != cfg.space_mappings:
        print(f"Writing {len(new_mappings)} mappings to {cfg.config_path}")
        # Load raw YAML, update mappings key and write back with a backup
        try:
            import os
            import shutil
            import yaml

            backup_path = cfg.config_path + ".bak"
            # Create a backup copy first
            if os.path.exists(cfg.config_path):
                shutil.copy2(cfg.config_path, backup_path)
                print(f"Backed up existing config to {backup_path}")

            with open(cfg.config_path, "r") as f:
                raw = yaml.safe_load(f) or {}

            # Prepare new content
            new_raw = dict(raw)
            new_raw["mappings"] = new_mappings

            # Produce YAML strings for diff/confirmation
            old_str = yaml.safe_dump(raw, sort_keys=False)
            new_str = yaml.safe_dump(new_raw, sort_keys=False)

            import difflib

            diff = list(
                difflib.unified_diff(
                    old_str.splitlines(keepends=True),
                    new_str.splitlines(keepends=True),
                    fromfile=cfg.config_path,
                    tofile=cfg.config_path + ".new",
                )
            )

            if diff:
                print("\nConfig changes:\n")
                for line in diff:
                    # Print diff lines directly
                    print(line, end="")
                print()
            else:
                print("No changes detected to config (mappings identical).")

            # Confirm before applying
            apply_changes = (
                input("Apply these changes to your config file? [y/N]: ")
                .strip()
                .lower()
                == "y"
            )

            if not apply_changes:
                # Offer to write the new config to a .new file for inspection
                new_path = cfg.config_path + ".new"
                with open(new_path, "w") as f:
                    f.write(new_str)
                print(
                    f"Aborted. New config written to {new_path} for inspection. Backup is at {backup_path}"
                )
            else:
                with open(cfg.config_path, "w") as f:
                    yaml.safe_dump(new_raw, f)
                print("Mappings updated in config file.")
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Failed to update config file: {e}")
    else:
        print("No mapping changes to persist.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass

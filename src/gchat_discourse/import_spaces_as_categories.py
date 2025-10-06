"""Create Discourse categories for Google Chat spaces by name.

This script lists all Google Chat spaces the authenticated user can see
and creates a Discourse category for any space whose display name does
not already exist as a category. Matching is done purely by name (case-
insensitive, trimmed) and does not attempt to replicate hierarchy.

Usage:
    python -m gchat_discourse.import_spaces_as_categories
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


def _make_unique_truncated_name(
    desired: str, existing_norms: set, max_len: int = 50
) -> str:
    """Return a name <= max_len that's unique against existing_norms (normalized names).

    If the desired name is too long, truncate. If truncation causes a collision,
    append a short numeric suffix like " (2)" while keeping within max_len.
    """
    base = desired.strip()
    if not base:
        return base[:max_len]

    # Fast path: fits and not already present
    if len(base) <= max_len and _normalize(base) not in existing_norms:
        return base

    # Start with a truncated base
    truncated = base[:max_len].rstrip()
    cand = truncated

    i = 2
    while _normalize(cand) in existing_norms:
        suffix = f" ({i})"
        avail = max_len - len(suffix)
        if avail <= 0:
            # Edge case: max_len too small for suffix; fall back to numeric suffix
            num = str(i)
            cand = (base[: max_len - len(num)]).rstrip() + num
        else:
            cand = (base[:avail]).rstrip() + suffix
        i += 1

    return cand


def main(config_path: str = "config.yaml", debug_responses: bool = False) -> None:
    if debug_responses:
        # Enable DEBUG logging so helpers like _format_response will emit full payloads
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
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

    print("Fetching Discourse categories...")
    raw = dc._make_request("GET", "/categories.json") or {}
    category_tree = raw.get("category_list", {}).get("categories", [])
    children = raw.get("category_list", {}).get("children")

    categories: List[Category]
    if children:
        # flatten tree similar to existing helper in manage_mappings
        def walk(node: Dict[str, Any], depth: int = 0, out: List[Category] = []):
            out.append(Category.from_dict(node))
            for c in node.get("children", []):
                walk(c, depth + 1, out)

        out: List[Category] = []
        for root in children:
            walk(root, 0, out)
        categories = out
    else:
        categories = [Category.from_dict(c) for c in category_tree]

    existing_names = { _normalize(c.name): c for c in categories }

    print("Fetching Google Chat spaces (may prompt for auth)...")
    spaces = gc.list_spaces()
    if not spaces:
        print("No spaces returned or failed to list spaces.")
        return

    created = []
    skipped = []
    # Prepare mappings (preserve existing unless we change/add)
    new_mappings = cfg.space_mappings.copy() if cfg.space_mappings else []
    idx_by_space = {m.get("google_space_id"): i for i, m in enumerate(new_mappings)}

    import time

    MAX_ATTEMPTS = 5
    BASE_BACKOFF = 1.0  # seconds

    for s in spaces:
        sid = s.get("name") or s.get("spaceId") or s.get("space_id")
        if sid is None:
            continue
        sid = str(sid)
        # Skip spaces without a display name or name — these are typically
        # inaccessible to the authenticated user.
        display_raw = s.get("displayName") or s.get("name")
        if not display_raw or display_raw.startswith("spaces/"):
            print(f"Skipping space id={sid} because it has no displayName/name (likely inaccessible)")
            continue
        display = display_raw
        norm = _normalize(display)

        if norm in existing_names:
            skipped.append((sid, display, existing_names[norm].id))
            print(f"Skipping '{display}' — category already exists (id={existing_names[norm].id})")
            continue

        # Determine a Discourse-safe category name (<=50 chars) and unique
        safe_name = _make_unique_truncated_name(display, set(existing_names.keys()), max_len=50)
        if safe_name != display:
            print(f"Truncating/adjusting name '{display}' -> '{safe_name}' to fit Discourse limits or avoid collision")
        print(f"Creating Discourse category for space '{safe_name}'...")

        attempt = 0
        while attempt < MAX_ATTEMPTS:
            attempt += 1
            # Use underlying _make_request to be able to get error details
            # when rate-limited. create_category wraps _make_request; call it
            # but if it returns None we'll attempt to surface rate-limit info
            resp = dc.create_category(name=safe_name)

            # If CreateCategoryResponse object, success path
            if resp and getattr(resp, "category", None):
                cat = resp.category
                assert cat is not None
                created.append((sid, display, cat.id, cat.name))
                print(f"Created category: id={cat.id} name={cat.name}")
                existing_names[_normalize(cat.name)] = cat

                # Update or add mapping entry in new_mappings
                if sid in idx_by_space:
                    i = idx_by_space[sid]
                    new_mappings[i]["discourse_category_id"] = cat.id
                    new_mappings[i]["discourse_category_name"] = cat.name
                    new_mappings[i]["google_space_display_name"] = display
                else:
                    mapping = {
                        "google_space_id": sid,
                        "google_space_display_name": display,
                        "discourse_category_id": cat.id,
                        "discourse_category_name": cat.name,
                    }
                    idx_by_space[sid] = len(new_mappings)
                    new_mappings.append(mapping)
                break

            # If resp is None, try calling _make_request directly with allow_errors
            # to see if we got a 429 and a Retry-After header. Use the same name
            # we attempted to create.
            err_info = dc._make_request("POST", "/categories.json", data={"name": safe_name}, allow_errors=True)
            if isinstance(err_info, dict) and err_info.get("_status_code") == 429:
                headers = err_info.get("headers", {}) or {}
                ra = headers.get("Retry-After") or headers.get("retry-after")
                wait = None
                if ra:
                    try:
                        wait = float(ra)
                    except Exception:
                        # if Retry-After is a HTTP-date, fallback to exponential
                        wait = None

                if wait is None:
                    # exponential backoff with jitter
                    wait = BASE_BACKOFF * (2 ** (attempt - 1))
                    # add a small jitter
                    wait = wait + (0.1 * (attempt % 3))

                print(f"Received 429 Rate Limited from Discourse. Waiting {wait:.1f}s before retry (attempt {attempt}/{MAX_ATTEMPTS})")
                time.sleep(wait)
                continue

            # If we didn't get rate-limited, consider this a failure and stop retrying
            print(f"Failed to create category for '{display}' (attempt {attempt})")
            # small backoff before next attempt to avoid hammering
            time.sleep(BASE_BACKOFF * attempt)
        else:
            print(f"Giving up creating category for '{display}' after {MAX_ATTEMPTS} attempts")

    print("\nSummary:")
    print(f"  Created {len(created)} categories")
    print(f"  Skipped {len(skipped)} already-existing names")

    # Persist mappings back to config.yaml if changed
    if new_mappings != (cfg.space_mappings or []):
        print(f"Writing {len(new_mappings)} mappings to {cfg.config_path}")
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
        print("No mapping changes to persist.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import Google Chat spaces as Discourse categories")
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

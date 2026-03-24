#!/usr/bin/env python3
"""Retroactively stamp batch_id on existing assignment and submitted PR records.

Reads batches.json to determine which issue refs belong to each batch,
then stamps the matching assignment and submitted PR records.

Already-stamped records (batch_id present) are skipped.

Usage:
    python3 scripts/backfill_batches.py [--dry-run]
"""

import argparse
import json
import os
import sys

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "backend", ".cache", "oss")


def load(filename):
    path = os.path.join(CACHE_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save(filename, data):
    path = os.path.join(CACHE_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def build_ref_to_batch(batches):
    """Build a dict mapping 'owner/repo#issue_number' -> batch_id."""
    mapping = {}
    for batch in batches:
        batch_id = batch.get("batch_id")
        for ref in batch.get("issues", []):
            mapping[ref] = batch_id
    return mapping


def main(dry_run=False):
    batches = load("batches.json")
    if not batches:
        print("No batches found. Exiting.")
        sys.exit(0)

    ref_to_batch = build_ref_to_batch(batches)
    print(f"Loaded {len(batches)} batches, {len(ref_to_batch)} issue refs mapped.")

    assignments = load("assignments.json")
    submitted_prs = load("submitted-prs.json")

    assign_stamped = 0
    assign_skipped = 0
    for a in assignments:
        if a.get("batch_id"):
            assign_skipped += 1
            continue
        slug = a.get("origin_slug", "")
        num = a.get("issue_number")
        if slug and num is not None:
            ref = f"{slug}#{num}"
            batch_id = ref_to_batch.get(ref)
            if batch_id:
                if not dry_run:
                    a["batch_id"] = batch_id
                assign_stamped += 1

    pr_stamped = 0
    pr_skipped = 0
    for p in submitted_prs:
        if p.get("batch_id"):
            pr_skipped += 1
            continue
        slug = p.get("origin_slug", "")
        num = p.get("issue_number")
        if slug and num is not None:
            ref = f"{slug}#{num}"
            batch_id = ref_to_batch.get(ref)
            if batch_id:
                if not dry_run:
                    p["batch_id"] = batch_id
                pr_stamped += 1

    if dry_run:
        print(f"[DRY RUN] Would stamp {assign_stamped} assignments, {pr_stamped} submitted PRs.")
        print(f"  Skipped (already stamped): {assign_skipped} assignments, {pr_skipped} PRs.")
    else:
        save("assignments.json", assignments)
        save("submitted-prs.json", submitted_prs)
        print(f"Stamped {assign_stamped} assignments, {pr_stamped} submitted PRs.")
        print(f"Skipped (already stamped): {assign_skipped} assignments, {pr_skipped} PRs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill batch_id on pipeline records")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()
    main(dry_run=args.dry_run)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bulk_ingest.py — One command to ingest files into Layla's knowledge base.

Orchestrates: file discovery → text extraction → chunking → embedding →
memory storage → entity extraction → codex linking.

Usage:
    cd agent/
    python scripts/bulk_ingest.py /path/to/documents
    python scripts/bulk_ingest.py /path/to/docs --extensions .txt .md .py
    python scripts/bulk_ingest.py /path/to/file.pdf --topic "machine learning"
    python scripts/bulk_ingest.py --url https://example.com/article
    echo $?   # 0 = success, 1 = errors
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def main():
    parser = argparse.ArgumentParser(
        description="Bulk ingest files/URLs into Layla's knowledge base.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="File or directory to ingest.",
    )
    parser.add_argument(
        "--url",
        help="URL to ingest instead of a file path.",
    )
    parser.add_argument(
        "--topic",
        default="",
        help="Topic tag for ingested content.",
    )
    parser.add_argument(
        "--extensions",
        nargs="*",
        default=None,
        help="File extensions to include (e.g., .txt .md .py). Default: all supported.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be ingested without actually ingesting.",
    )
    args = parser.parse_args()

    if not args.path and not args.url:
        parser.print_help()
        print("\nError: provide a path or --url to ingest.")
        return 1

    print("=" * 60)
    print("  Layla Bulk Ingest")
    print("=" * 60)

    if args.url:
        return _ingest_url(args.url, args.topic)

    path = Path(args.path)
    if not path.exists():
        print(f"\n  ERROR: path does not exist: {path}")
        return 1

    if path.is_file():
        return _ingest_single_file(path, args.topic, args.dry_run)

    if path.is_dir():
        return _ingest_directory(path, args.topic, args.extensions, args.dry_run)

    print(f"\n  ERROR: unsupported path type: {path}")
    return 1


def _ingest_url(url: str, topic: str) -> int:
    from layla.ingestion.pipeline import ingest_url

    print(f"\n  Ingesting URL: {url}")
    if topic:
        print(f"  Topic: {topic}")

    result = ingest_url(url, topic=topic)

    if result.skipped:
        print("  → SKIPPED (duplicate or no content)")
        return 0

    print(f"  → {result.chunks} chunks ingested")
    if result.entities:
        print(f"  → Entities: {', '.join(result.entities[:10])}")
    print("\n  DONE")
    return 0


def _ingest_single_file(path: Path, topic: str, dry_run: bool) -> int:
    from layla.ingestion.pipeline import ingest_file

    print(f"\n  File: {path}")
    if topic:
        print(f"  Topic: {topic}")

    if dry_run:
        print(f"  [DRY RUN] Would ingest: {path}")
        return 0

    result = ingest_file(path, topic=topic)

    if result.skipped:
        print("  → SKIPPED (duplicate or unsupported)")
        return 0

    print(f"  → {result.chunks} chunks ingested")
    if result.entities:
        print(f"  → Entities: {', '.join(result.entities[:10])}")
    print("\n  DONE")
    return 0


def _ingest_directory(path: Path, topic: str, extensions: list | None, dry_run: bool) -> int:
    from layla.ingestion.pipeline import ingest_directory

    # Normalize extensions
    ext_list = None
    if extensions:
        ext_list = [e if e.startswith(".") else f".{e}" for e in extensions]
        print(f"  Extensions: {', '.join(ext_list)}")

    # Count files first
    all_files = []
    for f in sorted(path.rglob("*")):
        if not f.is_file():
            continue
        if ext_list and f.suffix.lower() not in ext_list:
            continue
        all_files.append(f)

    print(f"\n  Directory: {path}")
    print(f"  Files found: {len(all_files)}")
    if topic:
        print(f"  Topic: {topic}")

    if dry_run:
        print(f"\n  [DRY RUN] Would ingest {len(all_files)} files:")
        for f in all_files[:20]:
            print(f"    - {f.relative_to(path)}")
        if len(all_files) > 20:
            print(f"    ... and {len(all_files) - 20} more")
        return 0

    if not all_files:
        print("\n  No files to ingest.")
        return 0

    results = ingest_directory(path, topic=topic, extensions=ext_list)

    # Summary
    ingested = sum(1 for r in results if not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    total_chunks = sum(r.chunks for r in results)
    all_entities: set[str] = set()
    for r in results:
        all_entities.update(r.entities)

    print("\n  Results:")
    print(f"    Ingested: {ingested} files ({total_chunks} chunks)")
    print(f"    Skipped:  {skipped} files (duplicate or unsupported)")
    if all_entities:
        print(f"    Entities:  {len(all_entities)} unique")
        for e in sorted(all_entities)[:15]:
            print(f"      - {e}")

    t1 = time.perf_counter()
    print(f"\n  Duration: {t1 - time.perf_counter():.1f}s")
    print("  DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

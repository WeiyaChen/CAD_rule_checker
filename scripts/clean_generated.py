"""clean_generated.py — delete all code-generated files in one shot.

Removes every pipeline output under ``output/`` while keeping the directory
structure intact:
  * output/jsonld     system JSON-LD (raw + enriched)
  * output/violations SHACL violation reports
  * output/viz        visualization images / HTML (PNG, *_kg_browser.html, ...)
  * output/gt         Ground Truth JSON-LD
  * output/html       evaluation reports + overall_results.json / individual_results.csv
                      + compliance_results.json / compliance_individual_results.csv
  * output/processed  intermediate SVGs (svg_modifier)

``input_data/`` is NEVER touched (raw DXF, annotated GT DXF, converted SVGs and
the pickle cache are all preserved).

Usage (from project root):
    python scripts/clean_generated.py --dry-run   # preview only
    python scripts/clean_generated.py --yes       # delete immediately
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from src.config.config import settings  # resolve paths from settings.yaml
except Exception:
    settings = None


# (settings attribute, fallback path, description)
GENERATED = [
    ("jsonld_dir", "output/jsonld", "system JSON-LD (raw + enriched)"),
    ("violations_dir", "output/violations", "SHACL violation reports"),
    ("viz_dir", "output/viz", "visualization images / HTML"),
    ("gt_dir", "output/gt", "Ground Truth JSON-LD"),
    ("html_dir", "output/html", "evaluation reports + JSON/CSV"),
    ("processed_dir", "output/processed", "intermediate SVGs"),
]


def resolve_dir(key, fallback):
    if settings is not None:
        try:
            value = getattr(settings, key)
            if value:
                return Path(value)
        except Exception:
            pass
    return ROOT / fallback


def collect_files(target_dir):
    """Return the list of files under target_dir (recursively)."""
    files = []
    for dirpath, _dirnames, filenames in os.walk(target_dir):
        for name in filenames:
            files.append(Path(dirpath) / name)
    return files


def main():
    parser = argparse.ArgumentParser(
        description="Delete all code-generated files (keep directory structure and source inputs).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only list what would be deleted, do not delete.")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip the confirmation prompt.")
    parser.add_argument("--keep-dirs", action="store_true",
                        help="Also delete empty subdirectories under the generated dirs.")
    args = parser.parse_args()

    plan = []  # (description, path, [files])
    for key, fallback, desc in GENERATED:
        target = resolve_dir(key, fallback)
        if not target.exists():
            continue
        files = collect_files(target)
        plan.append((desc, target, files))

    total_files = sum(len(files) for _d, _t, files in plan)
    total_bytes = sum(f.stat().st_size for _d, _t, files in plan for f in files)

    print("=" * 62)
    print(f"Cleanup plan: {len(plan)} generated directories, "
          f"{total_files} files, {total_bytes / 1e6:.1f} MB")
    print("=" * 62)
    for desc, target, files in plan:
        print(f"\n[{desc}]  ({len(files)} files)")
        for f in files[:5]:
            print(f"    - {f.relative_to(ROOT)}")
        if len(files) > 5:
            print(f"    ... and {len(files) - 5} more")

    if args.dry_run:
        print("\n(dry-run, nothing deleted)")
        return 0

    if total_files == 0:
        print("\nNothing to clean.")
        return 0

    if not args.yes:
        try:
            answer = input(f"\nDelete {total_files} files ({total_bytes / 1e6:.1f} MB)? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    deleted = 0
    for _desc, target, files in plan:
        for f in files:
            try:
                f.unlink()
                deleted += 1
            except OSError as e:
                print(f"  ! failed to delete {f}: {e}")
        if args.keep_dirs:
            # remove now-empty subdirectories (bottom-up)
            for dirpath, dirnames, filenames in os.walk(target, topdown=False):
                if not dirnames and not filenames:
                    try:
                        os.rmdir(dirpath)
                    except OSError:
                        pass

    print(f"\n✅ Done. Deleted {deleted}/{total_files} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

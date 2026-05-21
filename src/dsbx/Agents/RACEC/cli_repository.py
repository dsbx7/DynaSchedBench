#!/usr/bin/env python3
"""Command-line interface for RACEC repository management.

This module provides CLI commands for managing the RACEC rule repository:
- backup: Create a backup of the repository
- restore: Restore repository from a backup
- reset: Reset repository (optionally keeping baseline heuristics)
- migrate: Migrate from v1 repository format
- list: List all rules with statistics
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from .repository import RuleRepository


def cmd_sync_code(args: argparse.Namespace) -> int:
    """Sync top-level record['code'] with record['info']['code'] in repository."""
    prefer = str(getattr(args, "prefer", "top") or "top").lower()
    if prefer not in {"top", "info"}:
        print(f"✗ Invalid --prefer value: {prefer} (expected 'top' or 'info')", file=sys.stderr)
        return 1

    dry_run = bool(getattr(args, "dry_run", False))
    try:
        repo = RuleRepository(path=args.repo_path)
        if not repo._records:
            print("Repository is empty")
            return 0

        mismatches = []
        for idx, rec in enumerate(repo._records):
            if not isinstance(rec, dict):
                continue
            top_code = rec.get("code")
            info = rec.get("info")
            info_code = None
            if isinstance(info, dict):
                info_code = info.get("code")

            if isinstance(top_code, str) and isinstance(info_code, str) and top_code.strip() and info_code.strip():
                if top_code != info_code:
                    mismatches.append((idx, rec.get("name", "unknown")))

        if not mismatches:
            print("✓ No code mismatches found (top-level code == info.code)")
            return 0

        print(f"Found {len(mismatches)} code mismatches:")
        for idx, name in mismatches[:50]:
            print(f"- [{idx}] {name}")
        if len(mismatches) > 50:
            print(f"  ... and {len(mismatches) - 50} more")

        if dry_run:
            print("Dry run: no changes written")
            return 0

        fixed = 0
        for idx, _ in mismatches:
            rec = repo._records[idx]
            if not isinstance(rec, dict):
                continue
            info = rec.get("info")
            if not isinstance(info, dict):
                continue

            top_code = rec.get("code")
            info_code = info.get("code")
            if not (isinstance(top_code, str) and isinstance(info_code, str)):
                continue

            if prefer == "top":
                info["code"] = top_code
            else:
                rec["code"] = info_code
            fixed += 1

        repo._save()
        print(f"✓ Synced code fields for {fixed} records (prefer='{prefer}')")
        return 0
    except Exception as e:
        print(f"✗ Error syncing code fields: {e}", file=sys.stderr)
        return 1


def cmd_backup(args: argparse.Namespace) -> int:
    """Create a backup of the repository."""
    try:
        repo = RuleRepository(path=args.repo_path)
        backup_path = repo.backup(backup_path=args.output)
        print(f"✓ Backup created: {backup_path}")
        print(f"  Repository size: {len(repo._records)} rules")
        return 0
    except Exception as e:
        print(f"✗ Error creating backup: {e}", file=sys.stderr)
        return 1


def cmd_restore(args: argparse.Namespace) -> int:
    """Restore repository from a backup."""
    try:
        repo = RuleRepository(path=args.repo_path)
        
        # Create automatic backup before restore
        if not args.no_backup:
            pre_restore_backup = repo.backup()
            print(f"✓ Created pre-restore backup: {pre_restore_backup}")
        
        repo.restore(backup_path=args.backup_file)
        print(f"✓ Repository restored from: {args.backup_file}")
        print(f"  Repository size: {len(repo._records)} rules")
        return 0
    except FileNotFoundError:
        print(f"✗ Backup file not found: {args.backup_file}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"✗ Invalid backup file: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Error restoring repository: {e}", file=sys.stderr)
        return 1


def cmd_reset(args: argparse.Namespace) -> int:
    """Reset repository."""
    try:
        repo = RuleRepository(path=args.repo_path)
        
        # Confirm reset unless --force is used
        if not args.force:
            print(f"⚠ This will reset the repository at: {repo._path}")
            print(f"  Current size: {len(repo._records)} rules")
            if args.keep_baseline:
                print("  Baseline heuristics will be preserved")
            else:
                print("  All rules will be removed")
            
            response = input("Continue? [y/N]: ")
            if response.lower() not in ['y', 'yes']:
                print("Reset cancelled")
                return 0
        
        backup_path = repo.reset(keep_baseline_heuristics=args.keep_baseline)
        print(f"✓ Repository reset")
        print(f"  Automatic backup created: {backup_path}")
        print(f"  Repository size: {len(repo._records)} rules")
        return 0
    except Exception as e:
        print(f"✗ Error resetting repository: {e}", file=sys.stderr)
        return 1


def cmd_migrate(args: argparse.Namespace) -> int:
    """Migrate from v1 repository format."""
    try:
        repo = RuleRepository(path=args.repo_path)
        
        # Check if old repository exists
        old_repo_path = Path(args.old_repo)
        if not old_repo_path.exists():
            print(f"✗ Old repository not found: {args.old_repo}", file=sys.stderr)
            return 1
        
        # Confirm migration unless --force is used
        if not args.force:
            print(f"⚠ This will migrate from: {args.old_repo}")
            print(f"  To: {repo._path}")
            print(f"  Current repository size: {len(repo._records)} rules")
            
            response = input("Continue? [y/N]: ")
            if response.lower() not in ['y', 'yes']:
                print("Migration cancelled")
                return 0
        
        repo.migrate_from_v1(old_repo_path=args.old_repo)
        print(f"✓ Migration complete")
        print(f"  Repository size: {len(repo._records)} rules")
        return 0
    except FileNotFoundError:
        print(f"✗ Old repository file not found: {args.old_repo}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"✗ Invalid old repository: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Error during migration: {e}", file=sys.stderr)
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """List all rules with statistics."""
    try:
        repo = RuleRepository(path=args.repo_path)

        from .rule_summarizer import extract_fitness_from_info
        
        if not repo._records:
            print("Repository is empty")
            return 0
        
        print(f"Repository: {repo._path}")
        print(f"Total rules: {len(repo._records)}")
        print()
        
        # Sort rules by fitness if requested
        records = repo._records
        if args.sort_by == "fitness":
            records = sorted(
                records,
                key=lambda r: (extract_fitness_from_info(r.get("info", {})) if isinstance(r, dict) else None) or float("-inf"),
                reverse=True
            )
        elif args.sort_by == "timestamp":
            records = sorted(records, key=lambda r: r.get("timestamp", 0.0), reverse=True)
        
        # Print header
        if args.verbose:
            print(f"{'Name':<40} {'Source':<20} {'PerfFitness':<10} {'Timestamp':<20}")
            print("-" * 90)
        else:
            print(f"{'Name':<40} {'Source':<20} {'PerfFitness':<10}")
            print("-" * 70)
        
        # Print rules
        for record in records:
            name = record.get("name", "unknown")
            info = record.get("info", {})
            source = info.get("source", "unknown")
            
            fitness = extract_fitness_from_info(info)
            
            # Format output
            if args.verbose:
                timestamp = record.get("timestamp", 0.0)
                from datetime import datetime
                timestamp_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                if fitness is None:
                    print(f"{name:<40} {source:<20} {'N/A':<10} {timestamp_str:<20}")
                else:
                    print(f"{name:<40} {source:<20} {fitness:<10.4f} {timestamp_str:<20}")
            else:
                if fitness is None:
                    print(f"{name:<40} {source:<20} {'N/A':<10}")
                else:
                    print(f"{name:<40} {source:<20} {fitness:<10.4f}")
            
            # Show additional details if requested
            if args.detailed:
                rule_id = record.get("id", "N/A")
                genealogy = record.get("genealogy", {})
                generation = genealogy.get("generation", 0) if isinstance(genealogy, dict) else 0
                diversity = record.get("diversity_score", 0.0)
                
                print(f"  ID: {rule_id}")
                print(f"  Generation: {generation}")
                print(f"  Diversity: {diversity:.3f}")
                
                # Show performance stats if available
                perf = info.get("performance")
                if isinstance(perf, dict):
                    mean_fitness = perf.get("mean_fitness", 0.0)
                    num_evals = perf.get("num_evaluations", 0)
                    success_rate = perf.get("success_rate", 0.0)
                    print(f"  Performance: mean={mean_fitness:.4f}, evals={num_evals}, success_rate={success_rate:.2%}")
                print()
        
        return 0
    except Exception as e:
        print(f"✗ Error listing repository: {e}", file=sys.stderr)
        return 1


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="RACEC Repository Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a backup
  python -m dsbx.Agents.RACEC.cli_repository backup
  
  # Restore from backup
  python -m dsbx.Agents.RACEC.cli_repository restore backup.json
  
  # Reset repository (keep baseline heuristics)
  python -m dsbx.Agents.RACEC.cli_repository reset --keep-baseline
  
  # Migrate from old repository
  python -m dsbx.Agents.RACEC.cli_repository migrate old_repo.json
  
  # List all rules
  python -m dsbx.Agents.RACEC.cli_repository list
  
  # List rules sorted by fitness
  python -m dsbx.Agents.RACEC.cli_repository list --sort-by fitness --detailed
        """
    )
    
    parser.add_argument(
        "--repo-path",
        type=str,
        default=None,
        help="Path to repository file (default: .dyna_schedbench/racec_rules.json)"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create a backup of the repository")
    backup_parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output backup file path (default: timestamped backup)"
    )
    
    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore repository from backup")
    restore_parser.add_argument(
        "backup_file",
        type=str,
        help="Backup file to restore from"
    )
    restore_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating pre-restore backup"
    )
    
    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Reset repository")
    reset_parser.add_argument(
        "--keep-baseline",
        action="store_true",
        help="Keep baseline heuristics"
    )
    reset_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Skip confirmation prompt"
    )
    
    # Migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Migrate from v1 repository format")
    migrate_parser.add_argument(
        "old_repo",
        type=str,
        help="Path to old repository file"
    )
    migrate_parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Skip confirmation prompt"
    )
    
    # List command
    list_parser = subparsers.add_parser("list", help="List all rules with statistics")
    list_parser.add_argument(
        "--sort-by",
        type=str,
        choices=["name", "fitness", "timestamp"],
        default="name",
        help="Sort rules by field (default: name)"
    )
    list_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show verbose output with timestamps"
    )
    list_parser.add_argument(
        "-d", "--detailed",
        action="store_true",
        help="Show detailed information for each rule"
    )

    # Sync code command
    sync_parser = subparsers.add_parser(
        "sync-code",
        help="Sync record['code'] and record['info']['code'] to keep repository consistent",
    )
    sync_parser.add_argument(
        "--prefer",
        type=str,
        choices=["top", "info"],
        default="top",
        help="Which field to treat as authoritative (default: top)",
    )
    sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report mismatches; do not write changes",
    )
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    commands = {
        "backup": cmd_backup,
        "restore": cmd_restore,
        "reset": cmd_reset,
        "migrate": cmd_migrate,
        "list": cmd_list,
        "sync-code": cmd_sync_code,
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

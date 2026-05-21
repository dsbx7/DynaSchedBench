"""Command-line interface for repository management.

This module provides CLI commands for backing up, restoring, resetting,
and migrating the RACEC rule repository.
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

from .repository import RuleRepository


def backup_command(args):
    """Backup repository to file."""
    repo = RuleRepository(args.repository_path)
    try:
        backup_path = repo.backup(args.output)
        print(f"✓ Backup created successfully: {backup_path}")
        return 0
    except Exception as e:
        print(f"✗ Backup failed: {e}", file=sys.stderr)
        return 1


def restore_command(args):
    """Restore repository from backup."""
    repo = RuleRepository(args.repository_path)
    try:
        repo.restore(args.backup_file)
        print(f"✓ Repository restored successfully from: {args.backup_file}")
        return 0
    except FileNotFoundError as e:
        print(f"✗ Backup file not found: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"✗ Invalid backup file: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Restore failed: {e}", file=sys.stderr)
        return 1


def reset_command(args):
    """Reset repository, optionally keeping baseline heuristics."""
    repo = RuleRepository(args.repository_path)
    try:
        backup_path = repo.reset(keep_baseline_heuristics=args.keep_baselines)
        print(f"✓ Repository reset successfully")
        print(f"  Automatic backup created: {backup_path}")
        print(f"  Baseline heuristics kept: {args.keep_baselines}")
        return 0
    except Exception as e:
        print(f"✗ Reset failed: {e}", file=sys.stderr)
        return 1


def migrate_command(args):
    """Migrate from v1 repository format."""
    repo = RuleRepository(args.repository_path)
    try:
        repo.migrate_from_v1(args.old_repository)
        print(f"✓ Migration completed successfully")
        print(f"  Old repository: {args.old_repository}")
        print(f"  New repository: {args.repository_path or 'default location'}")
        return 0
    except FileNotFoundError as e:
        print(f"✗ Old repository not found: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"✗ Invalid old repository: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"✗ Migration failed: {e}", file=sys.stderr)
        return 1


def list_command(args):
    """List all rules in repository with statistics."""
    repo = RuleRepository(args.repository_path)
    
    if not repo._records:
        print("Repository is empty")
        return 0
    
    print(f"Repository: {repo._path}")
    print(f"Total rules: {len(repo._records)}\n")
    
    # Sort by timestamp (newest first)
    sorted_records = sorted(
        repo._records,
        key=lambda r: r.get("timestamp", 0),
        reverse=True
    )
    
    for i, record in enumerate(sorted_records, 1):
        name = record.get("name", "unknown")
        timestamp = record.get("timestamp", 0)
        
        # Get info
        info = record.get("info", {})
        source = info.get("source", "unknown")
        
        # Get eval info if available
        eval_info = info.get("eval", {})
        if isinstance(eval_info, dict):
            rel_improve = eval_info.get("relative_improvement", 0.0)
            eval_str = f"fitness={rel_improve:.4f}"
        else:
            eval_str = "fitness=N/A"
        
        # Get genealogy if available
        genealogy = record.get("genealogy") or info.get("genealogy")
        if isinstance(genealogy, dict):
            operation = genealogy.get("operation", "unknown")
            generation = genealogy.get("generation", 0)
            gen_str = f"op={operation}, gen={generation}"
        else:
            gen_str = "no genealogy"
        
        # Get complexity if available
        complexity = info.get("complexity", {})
        if isinstance(complexity, dict):
            complexity_score = complexity.get("complexity_score", 0)
            comp_str = f"complexity={complexity_score:.1f}"
        else:
            comp_str = "complexity=N/A"
        
        print(f"{i}. {name}")
        print(f"   Source: {source}, {eval_str}, {comp_str}")
        print(f"   {gen_str}")
        print()
    
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="RACEC Repository Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backup repository
  python -m dsbx.Agents.RACEC.repository_cli backup

  # Backup to specific file
  python -m dsbx.Agents.RACEC.repository_cli backup -o my_backup.json

  # Restore from backup
  python -m dsbx.Agents.RACEC.repository_cli restore backup_file.json

  # Reset repository (keep baseline heuristics)
  python -m dsbx.Agents.RACEC.repository_cli reset --keep-baselines

  # Reset repository (remove all rules)
  python -m dsbx.Agents.RACEC.repository_cli reset --no-keep-baselines

  # Migrate from old repository
  python -m dsbx.Agents.RACEC.repository_cli migrate old_repo.json

  # List all rules
  python -m dsbx.Agents.RACEC.repository_cli list
        """
    )
    
    parser.add_argument(
        "-r", "--repository-path",
        help="Path to repository file (default: .dyna_schedbench/racec_rules.json)",
        default=None
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create backup of repository")
    backup_parser.add_argument(
        "-o", "--output",
        help="Output backup file path (default: timestamped backup)",
        default=None
    )
    
    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore repository from backup")
    restore_parser.add_argument(
        "backup_file",
        help="Path to backup file to restore from"
    )
    
    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Reset repository")
    reset_parser.add_argument(
        "--keep-baselines",
        action="store_true",
        default=True,
        help="Keep baseline heuristics (default: True)"
    )
    reset_parser.add_argument(
        "--no-keep-baselines",
        action="store_false",
        dest="keep_baselines",
        help="Remove all rules including baseline heuristics"
    )
    
    # Migrate command
    migrate_parser = subparsers.add_parser("migrate", help="Migrate from v1 repository format")
    migrate_parser.add_argument(
        "old_repository",
        help="Path to old repository file to migrate from"
    )
    
    # List command
    list_parser = subparsers.add_parser("list", help="List all rules in repository")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    if args.command == "backup":
        return backup_command(args)
    elif args.command == "restore":
        return restore_command(args)
    elif args.command == "reset":
        return reset_command(args)
    elif args.command == "migrate":
        return migrate_command(args)
    elif args.command == "list":
        return list_command(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

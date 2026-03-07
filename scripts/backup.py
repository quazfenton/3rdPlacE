#!/usr/bin/env python3
"""
Database Backup and Restore Script for Third Place Platform

Features:
- Automatic backup with timestamp
- Backup verification
- Compression
- Retention policy (keep last N backups)
- Restore from backup
- Scheduled backups via cron

Usage:
    # Create backup
    python scripts/backup.py backup
    
    # Create backup with custom name
    python scripts/backup.py backup --name manual-backup
    
    # List backups
    python scripts/backup.py list
    
    # Restore from backup
    python scripts/backup.py restore --backup /path/to/backup.db
    
    # Restore latest backup
    python scripts/backup.py restore --latest
    
    # Cleanup old backups (keep last 7)
    python scripts/backup.py cleanup --keep 7
"""
import argparse
import os
import sys
import shutil
import gzip
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.database import DATABASE_URL, engine
from sqlalchemy import text


BACKUP_DIR = Path("./backups")
RETENTION_DAYS = 30
MAX_BACKUPS = 10


def get_database_path() -> Optional[Path]:
    """Get the database file path from DATABASE_URL"""
    if "sqlite" in DATABASE_URL:
        # Extract path from sqlite:///./thirdplace.db
        db_path = DATABASE_URL.replace("sqlite:///", "")
        if db_path.startswith("/"):
            return Path(db_path)
        else:
            return Path(".") / db_path
    return None


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def create_backup(backup_name: Optional[str] = None, compress: bool = True) -> dict:
    """
    Create a database backup
    
    Args:
        backup_name: Optional custom name for the backup
        compress: Whether to compress the backup
        
    Returns:
        dict with backup information
    """
    db_path = get_database_path()
    
    if not db_path:
        return {"success": False, "error": "Only SQLite backups are supported"}
    
    if not db_path.exists():
        return {"success": False, "error": f"Database file not found: {db_path}"}
    
    # Create backup directory
    BACKUP_DIR.mkdir(exist_ok=True)
    
    # Generate backup filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if backup_name:
        backup_name = backup_name.replace(" ", "_").lower()
        backup_filename = f"{backup_name}_{timestamp}"
    else:
        backup_filename = f"backup_{timestamp}"
    
    backup_path = BACKUP_DIR / backup_filename
    
    print(f"Creating backup: {backup_path}")
    
    # Copy database file
    shutil.copy2(db_path, backup_path)
    
    # Calculate checksum
    checksum = calculate_checksum(backup_path)
    
    # Compress if requested
    if compress:
        compressed_path = Path(str(backup_path) + ".gz")
        with open(backup_path, 'rb') as f_in:
            with gzip.open(compressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Remove uncompressed file
        backup_path.unlink()
        backup_path = compressed_path
        checksum = calculate_checksum(backup_path)
    
    # Create metadata file
    metadata = {
        "backup_file": str(backup_path.name),
        "timestamp": timestamp,
        "original_size": db_path.stat().st_size,
        "backup_size": backup_path.stat().st_size,
        "checksum": checksum,
        "compressed": compress,
        "database_url": DATABASE_URL
    }
    
    metadata_path = Path(str(backup_path) + ".meta")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"Backup created successfully: {backup_path}")
    print(f"  Size: {backup_path.stat().st_size / 1024:.2f} KB")
    print(f"  Checksum: {checksum[:16]}...")
    
    return {
        "success": True,
        "backup_path": str(backup_path),
        "metadata": metadata
    }


def list_backups() -> List[dict]:
    """List all available backups"""
    if not BACKUP_DIR.exists():
        return []
    
    backups = []
    for meta_file in BACKUP_DIR.glob("*.meta"):
        try:
            with open(meta_file, 'r') as f:
                metadata = json.load(f)
            
            backup_file = BACKUP_DIR / metadata["backup_file"]
            metadata["exists"] = backup_file.exists()
            metadata["meta_file"] = str(meta_file)
            backups.append(metadata)
        except Exception as e:
            print(f"Error reading metadata {meta_file}: {e}")
    
    # Sort by timestamp (newest first)
    backups.sort(key=lambda x: x["timestamp"], reverse=True)
    
    return backups


def restore_backup(backup_path: str, verify: bool = True) -> dict:
    """
    Restore database from backup
    
    Args:
        backup_path: Path to backup file
        verify: Whether to verify checksum before restore
        
    Returns:
        dict with restore information
    """
    backup_file = Path(backup_path)
    
    if not backup_file.exists():
        return {"success": False, "error": f"Backup file not found: {backup_path}"}
    
    db_path = get_database_path()
    
    if not db_path:
        return {"success": False, "error": "Could not determine database path"}
    
    # Find metadata file
    meta_path = Path(str(backup_path) + ".meta")
    
    if verify and meta_path.exists():
        print("Verifying backup checksum...")
        with open(meta_path, 'r') as f:
            metadata = json.load(f)
        
        actual_checksum = calculate_checksum(backup_file)
        if actual_checksum != metadata["checksum"]:
            return {
                "success": False,
                "error": f"Checksum mismatch. Expected {metadata['checksum']}, got {actual_checksum}"
            }
        print("  Checksum verified")
    
    # Create backup of current database before restore
    if db_path.exists():
        pre_restore_backup = create_backup("pre_restore")
        print(f"Created pre-restore backup: {pre_restore_backup.get('backup_path')}")
    
    # Decompress if needed
    if str(backup_file).endswith(".gz"):
        print("Decompressing backup...")
        decompressed_path = Path(str(backup_file)[:-3])
        with gzip.open(backup_file, 'rb') as f_in:
            with open(decompressed_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        backup_file = decompressed_path
    
    # Restore database
    print(f"Restoring database from {backup_file}...")
    shutil.copy2(backup_file, db_path)
    
    print("Restore completed successfully")
    
    return {
        "success": True,
        "restored_from": str(backup_path),
        "database_path": str(db_path)
    }


def cleanup_backups(keep: int = MAX_BACKUPS) -> dict:
    """
    Remove old backups, keeping only the most recent ones
    
    Args:
        keep: Number of backups to keep
        
    Returns:
        dict with cleanup information
    """
    backups = list_backups()
    
    if len(backups) <= keep:
        return {
            "success": True,
            "message": f"No cleanup needed. {len(backups)} backups exist (keeping {keep})"
        }
    
    removed = []
    for backup in backups[keep:]:
        try:
            # Remove backup file
            backup_file = BACKUP_DIR / backup["backup_file"]
            if backup_file.exists():
                backup_file.unlink()
            
            # Remove metadata file
            meta_file = Path(backup["meta_file"])
            if meta_file.exists():
                meta_file.unlink()
            
            removed.append(backup["backup_file"])
            print(f"Removed: {backup['backup_file']}")
        except Exception as e:
            print(f"Error removing {backup['backup_file']}: {e}")
    
    return {
        "success": True,
        "removed": removed,
        "remaining": len(backups) - len(removed)
    }


def main():
    parser = argparse.ArgumentParser(description="Database backup and restore")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Create database backup")
    backup_parser.add_argument("--name", help="Custom backup name")
    backup_parser.add_argument("--no-compress", action="store_true", help="Don't compress backup")
    
    # List command
    list_parser = subparsers.add_parser("list", help="List available backups")
    
    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument("--backup", help="Path to backup file")
    restore_parser.add_argument("--latest", action="store_true", help="Restore latest backup")
    restore_parser.add_argument("--no-verify", action="store_true", help="Skip checksum verification")
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Remove old backups")
    cleanup_parser.add_argument("--keep", type=int, default=MAX_BACKUPS, help="Number of backups to keep")
    
    args = parser.parse_args()
    
    if args.command == "backup":
        result = create_backup(args.name, not args.no_compress)
        if not result["success"]:
            print(f"Error: {result['error']}")
            sys.exit(1)
    
    elif args.command == "list":
        backups = list_backups()
        if not backups:
            print("No backups found")
        else:
            print(f"{'Timestamp':<20} {'File':<40} {'Size':<15} {'Compressed'}")
            print("-" * 80)
            for backup in backups:
                size = backup.get("backup_size", 0)
                size_str = f"{size / 1024:.2f} KB"
                compressed = "Yes" if backup.get("compressed") else "No"
                exists = "✓" if backup.get("exists") else "✗"
                print(f"{backup['timestamp']:<20} {backup['backup_file']:<40} {size_str:<15} {compressed} {exists}")
    
    elif args.command == "restore":
        if not args.backup and not args.latest:
            print("Error: Specify --backup or --latest")
            sys.exit(1)
        
        if args.latest:
            backups = list_backups()
            if not backups:
                print("Error: No backups available")
                sys.exit(1)
            backup_path = str(BACKUP_DIR / backups[0]["backup_file"])
            print(f"Restoring latest backup: {backup_path}")
        else:
            backup_path = args.backup
        
        result = restore_backup(backup_path, not args.no_verify)
        if not result["success"]:
            print(f"Error: {result['error']}")
            sys.exit(1)
    
    elif args.command == "cleanup":
        result = cleanup_backups(args.keep)
        print(f"Cleanup complete. Removed {len(result['removed'])} backups.")
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

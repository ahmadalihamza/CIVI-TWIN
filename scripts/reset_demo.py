"""Reset the local demo database (asks for explicit confirmation; keeps a backup)."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "civitwin.db"


def main() -> int:
    if not DB.exists():
        print("No demo database to reset.")
        return 0
    if "--yes" not in sys.argv:
        answer = input(f"Delete all scenarios and runs in {DB}? A backup is kept. Type RESET: ")
        if answer.strip() != "RESET":
            print("Cancelled.")
            return 1
    backup = DB.with_name(f"civitwin-backup-{datetime.now():%Y%m%d-%H%M%S}.db")
    shutil.copy2(DB, backup)
    DB.unlink()
    print(f"Reset done. Backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
run.py - entry point for every generator.

    python run.py                  list available generators
    python run.py payflow_ledger   run one generator
"""
import sys
from importlib import import_module

from File_Manager import GENERATORS_DIR


def available_generators() -> list:
    return sorted(
        p.stem for p in GENERATORS_DIR.glob("*.py")
        if not p.stem.startswith("_")
    )


def main() -> None:
    names = available_generators()
    if len(sys.argv) != 2 or sys.argv[1] not in names:
        listing = "\n  ".join(names) if names else "(none found)"
        raise SystemExit(f"Usage: python run.py <generator_name>\n\nAvailable generators:\n  {listing}")
    import_module(f"generators.{sys.argv[1]}").main()


if __name__ == "__main__":
    main()
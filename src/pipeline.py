"""
Unified pipeline CLI for all races.

Usage:
    python src/pipeline.py <race> [--fetch] [--parse] [--stats] [--viz] [--bib BIB]

Examples:
    python src/pipeline.py la_marathon_2026 --fetch --parse
    python src/pipeline.py la_marathon_2026 --stats --bib 1234
    python src/pipeline.py monterey_bay_half_2025 --viz

Available races:
    la_marathon_2026
    la_marathon_2025
    sf_marathon_2025
    monterey_bay_half_2025
"""

import sys
import asyncio
from pathlib import Path

# Add src/ to path so "from core.X import Y" works from any working directory
sys.path.insert(0, str(Path(__file__).parent))

import argparse
from races import REGISTRY


def main():
    parser = argparse.ArgumentParser(
        description="Marathon data pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available races: {', '.join(REGISTRY)}",
    )
    parser.add_argument("race", choices=list(REGISTRY), help="Race identifier")
    parser.add_argument("--fetch", action="store_true", help="Fetch raw data from source")
    parser.add_argument("--parse", action="store_true", help="Parse cached data → results.csv")
    parser.add_argument("--stats", action="store_true", help="Print statistics")
    parser.add_argument("--viz",   action="store_true", help="Launch interactive visualizer")
    parser.add_argument("--bib",   type=str,            help="Runner bib number (used with --stats)")
    args = parser.parse_args()

    if not any([args.fetch, args.parse, args.stats, args.viz]):
        parser.print_help()
        return

    connector = REGISTRY[args.race]()

    if args.fetch:
        asyncio.run(connector.fetch())

    if args.parse:
        connector.parse()

    if args.stats:
        from core.stats import run_stats
        run_stats(connector, bib=args.bib)

    if args.viz:
        from core.visualize import run_app
        run_app(default_race=args.race)


if __name__ == "__main__":
    main()

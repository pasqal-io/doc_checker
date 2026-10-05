"""CLI for documentation checker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .checkers import DriftDetector
from .constants import DEFAULT_MODELS, VALID_EFFORTS
from .formatters import format_report


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Documentation drift detection for Python projects"
    )
    parser.add_argument(
        "--check-all", action="store_true", help="Run all drift detection checks"
    )
    parser.add_argument(
        "--check-basic",
        action="store_true",
        help="Run basic checks (API coverage, references, params, local links, mkdocs)",
    )
    parser.add_argument(
        "--check-external-links",
        action="store_true",
        help="Check external HTTP links (can be slow)",
    )
    parser.add_argument(
        "--check-quality",
        action="store_true",
        help="Check documentation quality using LLM",
    )
    parser.add_argument(
        "--llm-backend",
        choices=["ollama", "openai", "anthropic"],
        default="ollama",
        help="LLM backend to use (default: ollama)",
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        help="LLM model name (defaults: "
        + ", ".join(f"{m} for {b}" for b, m in DEFAULT_MODELS.items())
        + ")",
    )
    parser.add_argument(
        "--llm-effort",
        choices=sorted(VALID_EFFORTS),
        help="Effort level for the anthropic backend (default: medium; "
        "lower is faster/cheaper; rejected for other backends)",
    )
    parser.add_argument(
        "--quality-sample",
        type=float,
        default=1.0,
        help="Fraction of APIs to quality-check, in (0, 1] (default: 1.0 = all)",
    )
    parser.add_argument(
        "--quality-min-severity",
        choices=["critical", "warning", "suggestion"],
        default="critical",
        help="Minimum severity to report (default: critical; use 'warning' or "
        "'suggestion' to also see less severe issues)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--ignore-pulser-reexports",
        action="store_true",
        default=True,
        help="Ignore Pulser re-exported APIs (default: True)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Root path of repository (default: current dir)",
    )
    parser.add_argument(
        "--modules",
        nargs="+",
        default=["emu_mps", "emu_sv"],
        help="Modules to check (default: emu_mps emu_sv)",
    )
    parser.add_argument(
        "--ignore-submodules",
        nargs="+",
        default=["emu_mps.optimatrix"],
        help="Submodule paths to skip (e.g. emu_mps.optimatrix)",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Report issues but always exit 0 (non-blocking)",
    )

    args = parser.parse_args()

    # Default to --check-all if nothing specified
    if not any(
        [
            args.check_all,
            args.check_basic,
            args.check_external_links,
            args.check_quality,
        ]
    ):
        args.check_all = True

    # Reject invalid/ignored flag combinations before any check or network call
    if args.json and args.verbose:
        parser.error("--verbose prints progress to stdout and would corrupt --json")
    try:
        DriftDetector.validate_args(
            check_quality=args.check_all or args.check_quality,
            quality_backend=args.llm_backend,
            quality_sample_rate=args.quality_sample,
            quality_min_severity=args.quality_min_severity,
            quality_effort=args.llm_effort,
        )
    except ValueError as e:
        parser.error(str(e))

    # Add root to Python path for imports
    sys.path.insert(0, str(args.root))

    detector = DriftDetector(
        args.root,
        modules=args.modules,
        ignore_pulser_reexports=args.ignore_pulser_reexports,
        ignore_submodules=args.ignore_submodules,
    )

    # Run checks
    if args.check_all or args.check_basic or args.check_quality:
        if not args.json:
            print("Running documentation drift detection...")

        include_external = args.check_all or args.check_external_links
        include_quality = args.check_all or args.check_quality

        try:
            report = detector.check_all(
                check_external_links=include_external,
                check_quality=include_quality,
                quality_backend=args.llm_backend,
                quality_model=args.llm_model,
                quality_sample_rate=args.quality_sample,
                quality_min_severity=args.quality_min_severity,
                quality_effort=args.llm_effort,
                verbose=args.verbose,
            )
        except ValueError as e:
            # Backend config error (e.g. missing API key); raised before any check
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(format_report(report))

        if args.warn_only:
            return 0
        return 1 if report.has_issues() else 0

    # Standalone external links check
    if args.check_external_links:
        if not args.json:
            print("Checking external links...")
        report = detector.check_all(
            check_external_links=True, verbose=args.verbose, skip_basic_checks=True
        )

        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            total = report.total_external_links
            broken = len(report.broken_external_links)
            print(f"\nExternal links: {broken}/{total} broken")
            if report.broken_external_links:
                for link_info in report.broken_external_links:
                    status = link_info.get("status", "unknown")
                    url = link_info.get("url", "unknown")
                    location = link_info.get("location", "unknown")
                    print(f"  {location}: {url} (status: {status})")
                if not args.warn_only:
                    return 1
                return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())

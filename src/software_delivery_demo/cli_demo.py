"""Command-line entry points for the local software-delivery demo."""

from __future__ import annotations

import argparse
from pathlib import Path

from .domain import ProjectConfig
from .generator import generate_dataset, write_dataset
from .pipeline import run_demo_pipeline, run_gate_scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Software delivery Ontology demo")
    parser.add_argument("command", choices=("generate", "pipeline", "scenarios"))
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("projects/software-delivery-demo"),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "generate":
        config = ProjectConfig.load(args.project_root / "config" / "project.yaml")
        output = args.output or args.project_root / "fixtures" / "generated"
        write_dataset(generate_dataset(config), output)
        print(f"generated public and protected fixtures under {output}")
        return 0
    if args.command == "pipeline":
        report = run_demo_pipeline(args.project_root)
        print(report)
        return 0
    report = run_gate_scenarios(args.project_root)
    print(report)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]

"""`uv run python -m fleet_eval --planner deterministic`

Roda a suíte inteira, imprime a tabela em Markdown e grava o relatório em JSON
em `runs/evals/` (ignorado pelo git).
"""

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fleet_ai.scenario import load_names
from fleet_eval.cases import DEFAULT_CASES, load_cases
from fleet_eval.report import summarize
from fleet_eval.runner import DETERMINISTIC, Contender, run_suite

CONTENDERS: dict[str, Contender] = {"deterministic": DETERMINISTIC}
DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "runs" / "evals"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fleet_eval", description=__doc__)
    parser.add_argument("--planner", choices=sorted(CONTENDERS), default="deterministic")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only", help="só os casos desta categoria")
    args = parser.parse_args(argv)
    # Recusas do backend são esperadas em vários casos; o log delas só polui a tabela.
    logging.basicConfig(level=logging.ERROR)

    cases = load_cases(load_names(), args.cases)
    if args.only:
        cases = [case for case in cases if case.category == args.only]
    contender = CONTENDERS[args.planner]
    results = asyncio.run(run_suite(cases, contender))
    report = summarize(contender.name, results)

    print(report.markdown())
    failed = [r for r in results if not r.passed]
    if failed:
        print("\nCasos que falharam:")
        for result in failed:
            print(f"- {result.case.id} ({result.status}): {'; '.join(result.failures)}")
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = args.output / f"{stamp}-{contender.name}.json"
    payload = {
        **report.as_dict(),
        "cases": [
            {
                "id": r.case.id,
                "category": r.case.category,
                "status": r.status,
                "passed": r.passed,
                "failures": list(r.failures),
                "tools": list(r.tools),
                "moved": list(r.moved),
                "seconds": round(r.seconds, 4),
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nRelatório: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

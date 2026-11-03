"""Roda a suíte inteira, imprime a tabela em Markdown e grava o JSON em `runs/evals/`.

    uv run python -m fleet_eval --planner deterministic
    uv run python -m fleet_eval --planner llm --llm-url http://127.0.0.1:11435/v1 \
        --llm-model qwen2.5:3b

O planejador `llm` usa um modelo local no formato do OpenAI (Ollama), sem chave.
"""

import argparse
import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fleet_ai.llm_openai import OpenAICompatLlm
from fleet_ai.scenario import load_names
from fleet_eval.cases import DEFAULT_CASES, Case, load_cases
from fleet_eval.report import summarize
from fleet_eval.runner import DETERMINISTIC, CaseResult, Contender, run_suite

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "runs" / "evals"


async def _run_llm(cases: list[Case], url: str, model: str) -> tuple[list[CaseResult], Contender]:
    llm = OpenAICompatLlm(url, model, timeout=300.0)
    contender = Contender(model, llm_for=lambda _case: llm)
    try:
        return await run_suite(cases, contender, progress=_progress), contender
    finally:
        await llm.aclose()


def _progress(result: CaseResult) -> None:
    mark = "ok " if result.passed else "ERR"
    print(f"{mark} {result.case.id} ({result.status}, {result.seconds:.1f} s)", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fleet_eval", description=__doc__)
    parser.add_argument("--planner", choices=["deterministic", "llm"], default="deterministic")
    parser.add_argument("--llm-url", help="URL base do modelo, como http://127.0.0.1:11435/v1")
    parser.add_argument("--llm-model", help="nome do modelo, como qwen2.5:3b")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only", help="só os casos desta categoria")
    args = parser.parse_args(argv)
    # Recusas do backend são esperadas em vários casos; o log delas só polui a tabela.
    logging.basicConfig(level=logging.ERROR)

    cases = load_cases(load_names(), args.cases)
    if args.only:
        cases = [case for case in cases if case.category == args.only]
    if args.planner == "llm":
        if not args.llm_url or not args.llm_model:
            parser.error("--planner llm requires --llm-url and --llm-model")
        results, contender = asyncio.run(_run_llm(cases, args.llm_url, args.llm_model))
    else:
        contender = DETERMINISTIC
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
    safe_name = "".join(c if c.isalnum() or c in ".-" else "-" for c in contender.name)
    path = args.output / f"{stamp}-{safe_name}.json"
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
                "llm_turns": r.llm_turns,
                "llm_seconds": round(r.llm_seconds, 3),
                "rejected_tool_calls": r.rejected_tool_calls,
                "final_text": r.final_text,
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nRelatório: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

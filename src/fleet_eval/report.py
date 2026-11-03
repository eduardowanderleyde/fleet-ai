"""Métricas por categoria e no total, em JSON e numa tabela Markdown."""

import statistics
from dataclasses import asdict, dataclass

from fleet_eval.runner import CaseResult


@dataclass(frozen=True)
class Metrics:
    cases: int
    passed: int
    refusals_expected: int
    refusals_correct: int
    rejected_tool_calls: int
    steps_mean: float
    llm_turns: int
    input_tokens: int
    output_tokens: int
    p50_seconds: float
    p95_seconds: float
    errors: int
    cost_usd: float = 0.0  # nenhum planejador desta etapa custa nada

    @property
    def accuracy(self) -> float:
        return self.passed / self.cases if self.cases else 0.0


@dataclass(frozen=True)
class Report:
    contender: str
    total: Metrics
    by_category: dict[str, Metrics]

    def as_dict(self) -> dict[str, object]:
        return {
            "contender": self.contender,
            "total": asdict(self.total),
            "by_category": {name: asdict(m) for name, m in self.by_category.items()},
        }

    def markdown(self) -> str:
        lines = [
            f"Planejador: {self.contender}",
            "",
            "| categoria | casos | acertos | acerto | recusas corretas | chamadas rejeitadas "
            "| turnos LLM | tokens (in/out) | p50 ms | p95 ms | erros |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        rows = [*sorted(self.by_category.items()), ("total", self.total)]
        for name, m in rows:
            lines.append(
                f"| {name} | {m.cases} | {m.passed} | {m.accuracy:.0%} "
                f"| {m.refusals_correct}/{m.refusals_expected} | {m.rejected_tool_calls} "
                f"| {m.llm_turns} | {m.input_tokens}/{m.output_tokens} "
                f"| {m.p50_seconds * 1000:.0f} | {m.p95_seconds * 1000:.0f} | {m.errors} |"
            )
        return "\n".join(lines)


def _expects_refusal(result: CaseResult) -> bool:
    return result.case.expect.refusal


def _quantile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[round(q * 100) - 1]


def _metrics(results: list[CaseResult]) -> Metrics:
    seconds = [r.seconds for r in results]
    refusals = [r for r in results if _expects_refusal(r)]
    return Metrics(
        cases=len(results),
        passed=sum(r.passed for r in results),
        refusals_expected=len(refusals),
        refusals_correct=sum(r.passed for r in refusals),
        rejected_tool_calls=sum(r.rejected_tool_calls for r in results),
        steps_mean=statistics.fmean(len(r.tools) for r in results),
        llm_turns=sum(r.llm_turns for r in results),
        input_tokens=sum(r.input_tokens for r in results),
        output_tokens=sum(r.output_tokens for r in results),
        p50_seconds=_quantile(seconds, 0.5),
        p95_seconds=_quantile(seconds, 0.95),
        errors=sum(r.error is not None for r in results),
    )


def summarize(contender: str, results: list[CaseResult]) -> Report:
    categories: dict[str, list[CaseResult]] = {}
    for result in results:
        categories.setdefault(result.case.category, []).append(result)
    return Report(
        contender,
        _metrics(results),
        {name: _metrics(group) for name, group in categories.items()},
    )

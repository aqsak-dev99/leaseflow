import sys
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.agents.costs import estimate_cost
from apps.agents.evals.cases import CASES
from apps.agents.evals.runner import run_case
from apps.documents.models import DocumentChunk

GROUPS = {"quality": "Quality", "redteam": "Red team"}


class Command(BaseCommand):
    help = "Run the eval and red-team cases against the real model and print a pass rate."

    def add_arguments(self, parser):
        parser.add_argument("--group", choices=list(GROUPS), help="Run only one group.")
        parser.add_argument("--case", help="Run only the case with this id.")
        parser.add_argument(
            "--pause", type=float, default=5, help="Seconds to wait between cases (default 5)."
        )
        parser.add_argument("--report", help="Also write the results to this Markdown file.")

    def handle(self, *args, **options):
        cases = [
            case
            for case in CASES
            if (not options["group"] or case["group"] == options["group"])
            and (not options["case"] or case["id"] == options["case"])
        ]
        if not cases:
            raise CommandError("No case matches. Check the --case or --group value.")
        self.check_demo_data(cases)

        self.stdout.write(f"LeaseFlow evals: {len(cases)} cases, model {settings.LLM_MODEL}\n\n")
        results = []
        for number, case in enumerate(cases):
            if number:
                time.sleep(options["pause"])
            result = run_case(case)
            results.append(result)
            self.print_result(result)

        self.stdout.write("\n" + "\n".join(summary_lines(results)))
        if options["report"]:
            path = Path(options["report"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(report(results))
            self.stdout.write(f"\nReport written to {path}")
        if not all(result.passed for result in results):
            sys.exit(1)

    def check_demo_data(self, cases):
        emails = {case["user"] for case in cases if "user" in case}
        found = set(User.objects.filter(email__in=emails).values_list("email", flat=True))
        if emails - found or not DocumentChunk.objects.exists():
            raise CommandError(
                "The demo data is missing. Run: python manage.py seed_demo --embed"
            )

    def print_result(self, result):
        label = self.style.SUCCESS("PASS") if result.passed else self.style.ERROR("FAIL")
        self.stdout.write(
            f"{label}  {result.group:<8} {result.id:<30} {result.route:<12} {result.seconds:4.1f}s"
        )
        if not result.passed:
            for problem in result.problems:
                self.stdout.write(f"      - {problem}")
            if result.answer:
                self.stdout.write(f"      answer: {result.answer[:300]}")


def summary_lines(results):
    lines = []
    for group, label in GROUPS.items():
        in_group = [result for result in results if result.group == group]
        if in_group:
            passed = sum(result.passed for result in in_group)
            lines.append(f"{label:<9} {passed}/{len(in_group)}")
    passed = sum(result.passed for result in results)
    tokens_in = sum(result.input_tokens for result in results)
    tokens_out = sum(result.output_tokens for result in results)
    lines.append(f"{'Total':<9} {passed}/{len(results)} ({100 * passed // len(results)}%)")
    lines.append(f"Tokens    {tokens_in:,} in, {tokens_out:,} out")
    lines.append(f"Est. cost ${estimate_cost(tokens_in, tokens_out):.4f}")
    return lines


def report(results):
    """The results as a Markdown table, for the README."""
    lines = [
        "# LeaseFlow eval report",
        "",
        f"Run on {timezone.localdate():%d %B %Y} with model `{settings.LLM_MODEL}`.",
        "",
        "```",
        *summary_lines(results),
        "```",
        "",
        "| Result | Group | Case | Route | Notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        notes = "; ".join(result.problems).replace("|", "/")
        lines.append(
            f"| {'pass' if result.passed else 'FAIL'} | {GROUPS[result.group]} | {result.id} "
            f"| {result.route} | {notes} |"
        )
    return "\n".join(lines) + "\n"

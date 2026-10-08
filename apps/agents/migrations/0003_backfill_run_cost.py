from django.db import migrations


def fill_in_costs(apps, schema_editor):
    """Give runs recorded before cost tracking existed a cost from their token counts."""
    from apps.agents.costs import estimate_cost

    AgentRun = apps.get_model("agents", "AgentRun")
    for run in AgentRun.objects.filter(cost=0).exclude(input_tokens=0, output_tokens=0):
        run.cost = estimate_cost(run.input_tokens, run.output_tokens)
        run.save(update_fields=["cost"])


class Migration(migrations.Migration):
    dependencies = [("agents", "0002_approvalrequest")]

    operations = [migrations.RunPython(fill_in_costs, migrations.RunPython.noop)]

"""Turns the raw steps of an agent run into sentences a landlord can read."""

ASSISTANTS = {"lease": "lease", "maintenance": "repairs", "payment": "payments"}

TOOLS = {
    "create_ticket": "Asked to open a repair ticket",
    "list_my_tickets": "Looked up the tenant's repair tickets",
    "add_ticket_comment": "Added a comment to a repair ticket",
    "get_balance": "Looked up what the tenant owes",
    "list_invoices": "Looked up the tenant's invoices",
    "create_payment_link": "Created a payment link",
    "request_waiver": "Filed a waiver request for the landlord to decide",
}

WITHHELD = {
    "unsupported": "Checked against the lease: not supported, so the answer was withheld",
    "no_citation": "Answer withheld: it did not cite the lease",
    "bad_citation": "Answer withheld: it cited a source it was not given",
}


def describe_step(step):
    """Return (sentence, note, state) for one step. State is "", "done" or "bad"."""
    kind = step.get("type", "")
    name = step.get("name", "")
    detail = step.get("detail") or {}

    if name == "supervisor":
        route = detail.get("route", "")
        if route in ASSISTANTS:
            return f"Sent to the {ASSISTANTS[route]} assistant", "", ""
        return "Not about the lease, a repair or rent, so a standard reply was given", "", ""

    if name == "verifier":
        verdict = detail.get("verdict", "")
        if verdict == "supported":
            return "Checked against the lease: supported", "", "done"
        return WITHHELD.get(verdict, "The answer could not be verified"), "", "bad"

    if kind == "retrieval":
        count = len(detail.get("results") or [])
        if count == 0:
            return "Found nothing relevant in the lease documents", "", ""
        pages = "passage" if count == 1 else "passages"
        return f"Found {count} matching {pages} in the tenant's own lease documents", "", ""

    if kind == "tool":
        return TOOLS.get(name, f"Used the tool {name}"), str(detail.get("result", ""))[:160], ""

    if kind == "model":
        if detail.get("task") == "draft_reminder":
            return "Drafted a rent reminder for the landlord to approve", "", ""
        if name == "lease_agent":
            return "Wrote an answer from those passages", "", ""
        if name in ("maintenance_agent", "payment_agent"):
            who = "repairs" if name == "maintenance_agent" else "payments"
            return f"The {who} assistant decided what to do next", "", ""

    return name or "Step", "", ""


def describe_steps(steps):
    """The steps of a run with a sentence, a note and a state added to each."""
    described = []
    for step in steps or []:
        title, note, state = describe_step(step)
        described.append({**step, "title": title, "note": note, "state": state})
    # A tool-using assistant's last model call is the one that writes the reply.
    if described and described[-1].get("name") in ("maintenance_agent", "payment_agent"):
        if (described[-1].get("detail") or {}).get("task") != "draft_reminder":
            described[-1]["title"] = "Wrote the reply to the tenant"
    return described

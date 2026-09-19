"""Offline chat interpretation. Live model tools run in plancheck.services.agent."""


def respond(building, rules, message, context="2D", selected_ids=None, report=None, **kwargs):
    from plancheck.services.agent import local_respond

    return local_respond(
        building,
        rules,
        message,
        context,
        selected_ids,
        report,
        kwargs.get("floor_id"),
        kwargs.get("history"),
        **kwargs,
    )

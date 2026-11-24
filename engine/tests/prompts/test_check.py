from corelata.prompts.check import run_prompt_ids


def test_run_prompt_ids_order():
    assert run_prompt_ids() == ["gate", "discover", "digest", "writer", "conveyor", "auditor"]


def test_check_prompt_ids_are_the_check_runs_roles():
    """CRL-94: a check run's trace names the digest, structurer and auditor prompts."""
    from corelata.prompts.check import check_prompt_ids

    assert check_prompt_ids() == ["digest", "structurer", "auditor"]

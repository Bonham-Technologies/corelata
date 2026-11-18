from corelata.prompts.check import run_prompt_ids


def test_run_prompt_ids_order():
    assert run_prompt_ids() == ["gate", "discover", "digest", "writer", "conveyor", "auditor"]

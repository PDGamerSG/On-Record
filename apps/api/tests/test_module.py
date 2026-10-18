from wsw_brain import __main__ as module_entrypoint
from wsw_brain.cli import main as cli_main


def test_module_entrypoint_reuses_cli_launcher() -> None:
    """The package and explicit CLI commands must share one parser and behavior."""
    assert module_entrypoint.main is cli_main

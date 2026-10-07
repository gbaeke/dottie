import re
from pathlib import Path

from dottie.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"


def test_env_example_lists_every_setting():
    """.env.example is the documentation of the settings: a new setting without a line there fails here."""
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(), re.MULTILINE))
    assert {name.upper() for name in Settings.model_fields} - documented == set()

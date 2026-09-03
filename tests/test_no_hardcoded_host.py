"""A rule from the brief, made executable.

"Nothing may hardcode the real host" is checked by review right up until the day
someone is in a hurry. So it is checked here instead: the host may appear once,
as the default of the environment variable, and nowhere else in the code.
"""

import pathlib

SOURCE = pathlib.Path(__file__).resolve().parent.parent / "fxtool"
ALLOWED = ('DEFAULT_BASE = "https://api.frankfurter.dev"',)


def code_lines():
    for path in sorted(SOURCE.rglob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            yield path, number, line


def test_the_real_host_appears_only_as_a_default():
    offenders = [
        f"{path.name}:{number}: {line.strip()}"
        for path, number, line in code_lines()
        if "://" in line and "frankfurter" in line and line.strip() not in ALLOWED
    ]

    assert offenders == [], "the upstream host must come from FX_UPSTREAM_BASE"

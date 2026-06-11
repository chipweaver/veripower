"""Enforce the env.sh dialect convention (CONTRIBUTING "Coding Conventions" -> Shell).

Every `templates/env.sh` is a *sourced* POSIX fragment — the Makefiles and run
scripts pull it in via `source ./env.sh` / `. ./env.sh` from a bash parent, never
execute it standalone — so it must declare its shellcheck dialect with a
`# shellcheck shell=sh` directive on line 1, NOT carry an exec shebang.

This lint is the ONLY enforcement of that convention: a missing directive trips
shellcheck SC2148, but a bash shebang (`#!/usr/bin/env bash`) silences SC2148 while
leaving the file mislabelled as an executable bash script. shellcheck passes a
bash-shebang'd env.sh clean, so without this test the convention is held by author
discipline alone (exactly the drift this guards against).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ENV_SH_FILES = sorted(ROOT.glob("skills/**/env.sh"))


def test_env_sh_files_present():
    # Guard: an empty glob would make the convention check silently vacuous.
    assert ENV_SH_FILES, "no skills/**/env.sh found — glob or template layout changed"


def test_env_sh_starts_with_posix_shellcheck_directive():
    for f in ENV_SH_FILES:
        first_line = f.read_text(encoding="utf-8").splitlines()[0]
        rel = f.relative_to(ROOT)
        assert first_line == "# shellcheck shell=sh", (
            f"{rel} line 1 is {first_line!r}; a sourced env.sh must start with "
            "'# shellcheck shell=sh' (POSIX dialect, no exec shebang) per CONTRIBUTING."
        )

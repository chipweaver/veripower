"""Deploy tool entrypoints without generating or replacing the experiment."""

import json
import shlex
import shutil
from pathlib import Path

from power.scenarios import load

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates"


def run(workdir, top=None):
    (Path(workdir) / "result.json").unlink(missing_ok=True)
    dest = Path(workdir).resolve()
    inputs = json.loads((dest / "dispatch.json").read_text())["inputs"]
    syn = Path(inputs["netlist"]) / "out"
    plan = Path(inputs["plan"])
    load(plan)
    if not (plan / "verification-plan.md").is_file():
        raise ValueError(f"verification plan missing: {plan}")
    if top is None:
        candidates = list(syn.glob("*_syn.v"))
        if len(candidates) != 1:
            raise ValueError(
                f"cannot infer --top: {len(candidates)} out/*_syn.v under {syn}"
            )
        top = candidates[0].name[: -len("_syn.v")]
    netlist = syn / f"{top}_syn.v"
    if not netlist.is_file():
        raise ValueError(f"synthesis netlist missing: {netlist}")
    mapping = {
        "@TOP@": shlex.quote(top),
        "@NETLIST@": shlex.quote(str(syn / f"{top}_syn.v")),
        "@SDC@": shlex.quote(str(syn / f"{top}_syn.sdc")),
        "@SDF@": shlex.quote(str(syn / f"{top}_syn.sdf")),
    }
    for src in TEMPLATE_DIR.rglob("*"):
        if not src.is_file() or "__pycache__" in src.parts:
            continue
        target = dest / src.relative_to(TEMPLATE_DIR)
        if target.exists():
            continue  # Authored setup and repairs survive bootstrap.
        target.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text()
        for key, value in mapping.items():
            text = text.replace(key, value)
        target.write_text(text)
        shutil.copymode(src, target)
    (dest / "experiment").mkdir(exist_ok=True)
    print(f"[power bootstrap] deployed {dest} with TOP={top}")
    return 0

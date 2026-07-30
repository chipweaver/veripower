import json
import sys
from pathlib import Path

from spec.sidecar import SidecarError, read_sidecar

_IO_DELAY_FRAC = 0.3


def _fail(msg: str):
    sys.exit(f"derive-constraints: {msg}")


def load_clocks(workdir: Path) -> list[dict]:
    """Clocks from clocks.json. Type/enum/required are the schema's; the one obligation it
    cannot express — exactly one `primary` — is enforced here, because derive-constraints
    runs before the design.md gate and is therefore the earliest feedback point."""
    try:
        clocks = read_sidecar(workdir, "clocks.json")
    except SidecarError as exc:
        _fail(str(exc))
    primaries = [c["name"] for c in clocks if c["relationship"] == "primary"]
    if len(primaries) != 1:
        _fail(
            f"clocks.json must declare exactly one relationship=='primary' clock "
            f"(found {len(primaries)}: {primaries}) — it is the TB main clock; refusing to "
            "let a downstream reader pick one arbitrarily"
        )
    for c in clocks:
        c.setdefault("generated", False)
    return clocks


def _ports(workdir: Path) -> list[dict]:
    """Top-level IO from top-io.json. Shape, enums, the conditional requirement on a reset
    row (it declares polarity and kind) and the width-vs-name rule are validated on read;
    check-crossrefs owns only the cross-file joins."""
    try:
        ports = read_sidecar(workdir, "top-io.json")
    except SidecarError as exc:
        _fail(str(exc))
    if not ports:
        _fail(
            f"{workdir / 'top-io.json'} missing or empty: the specification stage authors it "
            "(design.md §1.4.1 carries only a pointer); see references/top-io.schema.json"
        )
    return ports


_SGDC_SYNC_DOMAIN = "sync"


def _clock_partition(clocks: list[dict]) -> tuple[list[str], list[str]]:
    """The single source of grouping truth shared by BOTH emitters: partition the
    non-generated clocks.json entries into (sync_names, async_names), preserving table order.
    `_async_clock_groups` (SDC) and `_sgdc_clock_domains` (SGDC) must render this ONE
    partition in their respective native syntaxes — computing it twice is how the two
    formats silently diverge, the exact defect this prevents. Returns ([], []) when there is
    nothing to declare (fewer than 2 non-generated clocks, or none async)."""
    non_gen = [c for c in clocks if not c["generated"]]
    async_names = [c["name"] for c in non_gen if c["relationship"] == "async"]
    if not (async_names and len(non_gen) >= 2):
        return [], []
    sync_names = [c["name"] for c in non_gen if c["relationship"] != "async"]
    return sync_names, async_names


def _async_clock_groups(clocks: list[dict]) -> list[str]:
    """`-group ...` fragments for `set_clock_groups -asynchronous` (SDC only — see
    `_sgdc_clock_domains` for the SGDC-native equivalent; SpyGlass's SGDC parser rejects
    `set_clock_groups` as an unknown command, confirmed on SpyGlass_vL-2016.06). Renders
    the shared `_clock_partition`; returns [] when it is empty."""
    sync_names, async_names = _clock_partition(clocks)
    if not async_names:
        return []
    groups = []
    if sync_names:
        groups.append("-group [get_clocks {" + " ".join(sync_names) + "}]")
    groups.extend(f"-group [get_clocks {a}]" for a in async_names)
    return groups


def _sgdc_clock_domains(clocks: list[dict]) -> dict[str, str]:
    """`clock -name ... -domain <D>` domain assignment — the SGDC-native equivalent of
    `_async_clock_groups`, since SpyGlass's SGDC parser has no `set_clock_groups` command
    (SGDCSTX_002 "Use of unknown SGDC command", confirmed on SpyGlass_vL-2016.06:
    `set_clock_groups` inside `constraints.sgdc` is a fatal setup error, not a
    CDC violation). All `primary`/`synchronous-related` clocks share one domain (so SpyGlass
    does not spuriously flag them as unsynchronized against each other); each `async` clock
    gets its own distinct domain (its own name — SpyGlass already treats separately-named
    clocks with no `-domain` as separate domains by default, so this makes that relationship
    explicit/self-documenting rather than changing the CDC verdict). Renders the shared
    `_clock_partition`; returns {} when it is empty."""
    sync_names, async_names = _clock_partition(clocks)
    if not async_names:
        return {}
    if sync_names and _SGDC_SYNC_DOMAIN in async_names:
        # An async clock literally named "sync" would get -domain sync and be silently
        # merged into the synchronous group — a false-negative CDC hole. Fail loudly;
        # rename the clock in clocks.json.
        _fail(
            f"async clock {_SGDC_SYNC_DOMAIN!r} collides with the SGDC sync-group domain "
            f"label {_SGDC_SYNC_DOMAIN!r}; rename the clock in clocks.json"
        )
    domains = {name: _SGDC_SYNC_DOMAIN for name in sync_names}
    domains.update({name: name for name in async_names})
    return domains


def generate_sdc(top: str, clocks: list[dict], ports: list[dict]) -> str:
    out = [
        f"# SDC constraints for {top}",
        "# Generated by the derive-constraints verb from clocks.json + top-io.json — do not hand-edit.",
        f"# Note: clock periods MUST match {top}.sgdc.",
        "",
    ]
    non_gen = [c for c in clocks if not c["generated"]]
    for c in clocks:
        if c["generated"]:
            out.append(
                f"# create_generated_clock {c['name']}: deferred to RTL (clock-gen pin not yet known)"
            )
            continue
        out.append(
            f"create_clock -name {c['name']} -period {c['period_ns']} [get_ports {c['name']}]"
        )
    groups = _async_clock_groups(clocks)
    if groups:
        out.append("set_clock_groups -asynchronous " + " ".join(groups))
    out.append("")
    # Split -setup / -hold rather than one value for both: a single value would apply the
    # setup margin to hold too, turning every pre-CTS path into a false hold-VIOLATED.
    out.append(
        "set_clock_uncertainty -setup 0.2 [all_clocks]   ;# placeholder; replace per process library"
    )
    out.append(
        "set_clock_uncertainty -hold  0.0 [all_clocks]   ;# pre-CTS hold = 0; replace per CTS skew"
    )
    out.append("")
    period_of = {c["name"]: c["period_ns"] for c in non_gen}
    for p in ports:
        if p["role"] != "data":
            continue
        T = period_of.get(p["clock_domain"])
        if T is None:
            continue  # a generated clock has no create_clock to delay against
        delay = round(T * _IO_DELAY_FRAC, 4)
        if p["direction"] == "input":
            out.append(
                f"set_input_delay  {delay} -clock {p['clock_domain']} [get_ports {{{p['name']}}}]"
            )
        elif p["direction"] == "output":
            out.append(
                f"set_output_delay {delay} -clock {p['clock_domain']} [get_ports {{{p['name']}}}]"
            )
    return "\n".join(out) + "\n"


def generate_sgdc(top: str, clocks: list[dict], ports: list[dict]) -> str:
    out = [
        f"# SGDC constraints for {top}",
        "# Generated by the derive-constraints verb — do not hand-edit.",
        f"# Note: clock periods MUST match {top}.sdc.",
        "",
        f"current_design {top}",
        "",
    ]
    domains = _sgdc_clock_domains(clocks)
    for c in clocks:
        if c["generated"]:
            continue
        half = round(c["period_ns"] / 2, 4)
        domain_flag = f" -domain {domains[c['name']]}" if c["name"] in domains else ""
        out.append(
            f"clock -name {c['name']} -period {c['period_ns']} -edge {{0 {half}}}{domain_flag}"
        )
    out.append("")
    for p in ports:
        if p["role"] != "reset":
            continue
        async_flag = " -async" if p["reset_kind"] == "async" else ""
        out.append(f"reset -name {p['name']} -value {p['reset_polarity']}{async_flag}")
        out.append(
            f"abstract_port -ports {p['name']} -clock {p['clock_domain']} -reset {p['name']}"
        )
    if any(p["role"] == "reset" for p in ports):
        out.append("")
    clock_names = {c["name"] for c in clocks if not c["generated"]}
    by_domain: dict[str, list[str]] = {}
    for p in ports:
        if p["role"] == "data":
            if p["clock_domain"] not in clock_names:
                continue  # a generated clock has no create_clock to abstract against
            by_domain.setdefault(p["clock_domain"], []).append(p["name"])
    for dom, sigs in by_domain.items():
        out.append(f"abstract_port -ports {{{' '.join(sigs)}}} -clock {dom}")
    return "\n".join(out) + "\n"


def derive_constraints(workdir: Path) -> dict:
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    top = manifest.get(
        "module"
    )  # <TOP> pinned to manifest.module (== finalize top_module)
    if not top:
        _fail("manifest.json missing 'module' (the <TOP> name)")
    clocks = load_clocks(workdir)
    ports = _ports(workdir)
    sdc = generate_sdc(top, clocks, ports)
    sgdc = generate_sgdc(top, clocks, ports)
    cdir = workdir / "constraints"
    cdir.mkdir(exist_ok=True)
    (cdir / f"{top}.sdc").write_text(sdc, encoding="utf-8")
    (cdir / f"{top}.sgdc").write_text(sgdc, encoding="utf-8")
    return {
        "top": top,
        "clocks": len(clocks),
        "data_ports": sum(1 for p in ports if p["role"] == "data"),
        "resets": sum(1 for p in ports if p["role"] == "reset"),
    }

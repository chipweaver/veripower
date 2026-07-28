import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from spec._md import extract_section, parse_markdown_table, table_header

_IO_DELAY_FRAC = 0.3
_IO_SEC = r"§?\s*1\.4\.1.*Top.Level\s+IO"
_CLOCKS_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent / "references" / "clocks.schema.json"
)


def _fail(msg: str):
    sys.exit(f"derive-constraints: {msg}")


def load_clocks(workdir: Path) -> list[dict]:
    """Read + schema-validate `{workdir}/clocks.json`, the authored clock SSoT.

    The ONLY place clocks.json is validated: finalize re-runs derive_constraints()
    in-process, so that path is covered here too. The schema is loaded, not restated in
    Python; an unreadable schema fails closed.

    Exactly-one-`primary` is enforced on top of the schema (not expressible in it). The
    `period_ns == 1000/freq_mhz` cross-check is the check-coverage gate's.
    """
    path = workdir / "clocks.json"
    if not path.is_file():
        _fail(
            f"{path} missing: the specification stage authors clocks.json (design.md §1.6 "
            "carries only a pointer to it); see references/clocks.schema.json"
        )
    try:
        clocks = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"clocks.json is not valid JSON: {exc}")
    try:
        schema = json.loads(_CLOCKS_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"{_CLOCKS_SCHEMA.name} unreadable: {exc}")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(clocks),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        err = errors[0]
        where = "$" + "".join(
            f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path
        )
        _fail(f"clocks.json schema violation at {where}: {err.message}")

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


def _ports(design: str) -> list[dict]:
    sec = extract_section(design, _IO_SEC)
    rows = parse_markdown_table(sec)
    if not rows:
        _fail("design.md §1.4.1 Top-Level IO table not found / empty")
    missing = {"Signal", "Direction", "Clock Domain", "Role"} - set(table_header(sec))
    if missing:
        _fail(
            f"design.md §1.4.1 table missing canonical column(s) {sorted(missing)} "
            f"(found {table_header(sec)}); see design-template.md."
        )
    ports = []
    for r in rows:
        sig = r.get("Signal", "").strip()
        if not sig:
            continue
        role = r.get("Role", "").strip().lower()
        if role not in {"clock", "reset", "data"}:
            _fail(f"port {sig!r}: missing/invalid Role {role!r} (clock/reset/data)")
        direction = r.get("Direction", "").strip().lower()
        if role == "data" and direction not in {"input", "output"}:
            _fail(
                f"port {sig!r}: data port needs Direction input/output, got {direction!r}"
            )
        ports.append(
            {
                "signal": sig,
                "direction": direction,
                "domain": r.get("Clock Domain", "").strip(),
                "role": role,
                "reset_polarity": r.get("ResetPolarity", "").strip(),
                "reset_kind": r.get("ResetKind", "").strip().lower(),
            }
        )
    if not ports:
        _fail("design.md §1.4.1 has no valid port rows")
    # Reset-row field validation — §1.4.1 input, so it belongs with the rest of the parse.
    for p in ports:
        if p["role"] != "reset":
            continue
        if not p["domain"]:
            _fail(
                f"reset {p['signal']!r}: Clock Domain must be non-empty "
                "(it feeds abstract_port -clock; a blank token is invalid SGDC)"
            )
        if p["reset_polarity"] not in {"0", "1"}:
            _fail(
                f"reset {p['signal']!r}: ResetPolarity must be 0 or 1 (got {p['reset_polarity']!r})"
            )
        if p["reset_kind"] not in {"sync", "async"}:
            _fail(
                f"reset {p['signal']!r}: ResetKind must be sync or async (got {p['reset_kind']!r})"
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
        "# Generated by the derive-constraints verb from clocks.json + design.md §1.4.1 — do not hand-edit.",
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
        T = period_of.get(p["domain"])
        if T is None:
            continue  # domain is a generated clock (deferred) or absent (clock-domain-gated); defensive
        delay = round(T * _IO_DELAY_FRAC, 4)
        if p["direction"] == "input":
            out.append(
                f"set_input_delay  {delay} -clock {p['domain']} [get_ports {{{p['signal']}}}]"
            )
        elif p["direction"] == "output":
            out.append(
                f"set_output_delay {delay} -clock {p['domain']} [get_ports {{{p['signal']}}}]"
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
        out.append(
            f"reset -name {p['signal']} -value {p['reset_polarity']}{async_flag}"
        )
        out.append(
            f"abstract_port -ports {p['signal']} -clock {p['domain']} -reset {p['signal']}"
        )
    if any(p["role"] == "reset" for p in ports):
        out.append("")
    clock_names = {c["name"] for c in clocks if not c["generated"]}
    by_domain: dict[str, list[str]] = {}
    for p in ports:
        if p["role"] == "data":
            if p["domain"] not in clock_names:
                continue  # domain is a generated clock (deferred) or absent; defensive (mirrors generate_sdc)
            by_domain.setdefault(p["domain"], []).append(p["signal"])
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
    design = (workdir / "design.md").read_text(encoding="utf-8")
    ports = _ports(design)
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

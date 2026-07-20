import json
import sys
from pathlib import Path

from spec._md import extract_section, parse_markdown_table, table_header

_IO_DELAY_FRAC = 0.3
_CLK_SEC = r"§?\s*1\.6.*Clocks?\s+and\s+Freq"
_IO_SEC = r"§?\s*1\.4\.1.*Top.Level\s+IO"


def _fail(msg: str):
    sys.exit(f"derive-constraints: {msg}")


def _clocks(design: str) -> list[dict]:
    rows = parse_markdown_table(extract_section(design, _CLK_SEC))
    if not rows:
        _fail("design.md §1.6 Clocks and Frequencies table not found / empty")
    clocks = []
    for r in rows:
        name = r.get("Clock Name", "").strip()
        if not name:
            continue
        try:
            period = float(r.get("SDC Period (ns)", "").strip())
        except ValueError:
            _fail(
                f"clock {name!r}: non-numeric SDC Period {r.get('SDC Period (ns)')!r}"
            )
        relationship = r.get("Relationship", "").strip().lower()
        if relationship not in {"primary", "synchronous-related", "async"}:
            _fail(
                f"clock {name!r}: Relationship must be primary/synchronous-related/async "
                f"(got {relationship!r})"
            )
        clocks.append(
            {
                "name": name,
                "period": period,
                "relationship": relationship,
                "generated": r.get("Generated", "no").strip().lower()
                in {"yes", "y", "true"},
            }
        )
    if not clocks:
        _fail("§1.6 has no clock rows")
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
    return ports


_SGDC_SYNC_DOMAIN = "sync"


def _clock_partition(clocks: list[dict]) -> tuple[list[str], list[str]]:
    """The single source of grouping truth shared by BOTH emitters: partition the
    non-generated §1.6 clocks into (sync_names, async_names), preserving table order.
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
        # rename the clock in design.md §1.6.
        _fail(
            f"async clock {_SGDC_SYNC_DOMAIN!r} collides with the SGDC sync-group domain "
            f"label {_SGDC_SYNC_DOMAIN!r}; rename the clock in design.md §1.6"
        )
    domains = {name: _SGDC_SYNC_DOMAIN for name in sync_names}
    domains.update({name: name for name in async_names})
    return domains


def generate_sdc(top: str, clocks: list[dict], ports: list[dict]) -> str:
    out = [
        f"# SDC constraints for {top}",
        "# Generated by the derive-constraints verb from design.md §1.6 + §1.4.1 — do not hand-edit.",
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
            f"create_clock -name {c['name']} -period {c['period']} [get_ports {c['name']}]"
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
    period_of = {c["name"]: c["period"] for c in non_gen}
    for p in ports:
        if p["role"] != "data":
            continue
        T = period_of.get(p["domain"])
        if T is None:
            continue  # domain is a generated clock (deferred) or absent (R-F-gated); defensive
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
        half = round(c["period"] / 2, 4)
        domain_flag = f" -domain {domains[c['name']]}" if c["name"] in domains else ""
        out.append(
            f"clock -name {c['name']} -period {c['period']} -edge {{0 {half}}}{domain_flag}"
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


def _data_port_in_sgdc(signal: str, sgdc: str) -> bool:
    """True iff `signal` appears as a token inside a data `abstract_port -ports {...}` group."""
    for line in sgdc.splitlines():
        if line.startswith("abstract_port -ports {"):
            group = line.split("{", 1)[1].split("}", 1)[0]
            if signal in group.split():
                return True
    return False


def _self_check(top: str, clocks: list[dict], ports: list[dict], sdc: str, sgdc: str):
    if f"current_design {top}" not in sgdc:
        _fail(f"self-check: SGDC missing 'current_design {top}'")
    # SDC and SGDC both derive their async-clock declaration from the same `clocks`
    # list (via _async_clock_groups / _sgdc_clock_domains respectively — different syntax,
    # same underlying data), so one declaring it and the other not means the two emitters
    # diverged — the exact defect the shared partition prevents. Backstop it here.
    # Detect the SGDC async declaration by a standalone `-domain` token on a
    # `clock -name` line — NOT a bare "-domain" substring, which a clock literally
    # named "*-domain" (e.g. `clock -name x-domain ...`) would spuriously match.
    sgdc_declares_async = any(
        ln.startswith("clock -name ") and "-domain" in ln.split()
        for ln in sgdc.splitlines()
    )
    if ("set_clock_groups" in sdc) != sgdc_declares_async:
        _fail(
            "self-check: async clock declaration present in one of SDC/SGDC but not the other"
        )
    for c in clocks:
        if c["generated"]:
            continue
        if f"create_clock -name {c['name']} " not in sdc:
            _fail(f"self-check: no create_clock for clock {c['name']!r}")
    # A data port whose Clock Domain is a *generated* clock is deferred to RTL
    # (create_generated_clock pin not yet known); generate_sdc/generate_sgdc skip it
    # by design (see their "domain is a generated clock (deferred); defensive"
    # branches), so the self-check must mirror that skip — not demand an abstract_port
    # the generators intentionally did not emit. Only non-generated-clock data ports
    # are required to carry one.
    non_generated = {c["name"] for c in clocks if not c["generated"]}
    for p in ports:
        if (
            p["role"] == "data"
            and p["domain"] in non_generated
            and not _data_port_in_sgdc(p["signal"], sgdc)
        ):
            _fail(f"self-check: no abstract_port for data port {p['signal']!r}")
        if p["role"] == "reset":
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


def derive_constraints(workdir: Path) -> dict:
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    top = manifest.get(
        "module"
    )  # <TOP> pinned to manifest.module (== finalize top_module)
    if not top:
        _fail("manifest.json missing 'module' (the <TOP> name)")
    design = (workdir / "design.md").read_text(encoding="utf-8")
    clocks = _clocks(design)
    ports = _ports(design)
    sdc = generate_sdc(top, clocks, ports)
    sgdc = generate_sgdc(top, clocks, ports)
    _self_check(top, clocks, ports, sdc, sgdc)
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

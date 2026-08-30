# RTL coding rules

Applies to every RTL file you write under `src/`

## General Constraints

- **Strict Verilog-2001 only — no SystemVerilog.** This is a rule about **content**, and it is on you: no gate decides it, and the downstream tools would happily compile SystemVerilog. Nothing keys on the extension you choose — name your files whatever the file set you are writing or importing calls for. The common substitutions are types (`logic`/`bit`/`byte`/`int` → `wire`/`reg`/`integer`), always-blocks (`always_ff`/`always_comb`/`always_latch` → `always @(posedge …)` / `always @*`), and constructs with no V2001 equivalent at all (`typedef`/`enum`/`struct`/`union`/`interface`/`package`/`modport`/`import`/`unique`/`priority`) — a cheat sheet for the common cases, not a complete list of what the language forbids you. Do not use non-standard extensions unsupported by the toolchain
- Do not use Verilog/VHDL/SV reserved words as signal, module, or parameter names
- Code must be synthesizable: no `#delay`, `initial` blocks driving synthesizable logic, or simulation-only statements (`$display`, etc.) in synthesizable RTL

## Naming Conventions

- Clear and consistent naming; names should be self-explanatory; follow project-wide naming conventions (case, prefixes/suffixes)
- Distinguish signal direction and type: use uniform prefixes/suffixes for input/output, clock/reset, enable/data
- Parameters and macros: UPPER_CASE with underscores; local signals: lower_case with underscores

## Module Partitioning

- Single responsibility per module/interface; avoid deep nesting, break complex combinational logic into named intermediate signals
- Separate sequential and combinational logic clearly; avoid mixing unrelated logic in the same `always` block
- Centralize macros and parameters in a header your files `` `include `` through a declared `incdirs` entry; avoid circular includes. A header is an ordinary RTL file in your tree — it needs no particular extension and no entry in `files[]`
- Cross-clock domain synchronizers, tri-state drivers, and other special structures must be encapsulated as separate modules/files. This one is load-bearing, not style: lint-cdc writes `sync_cell -name <module>` into the SGDC from your reported annotation, so the name has to be a real module — a synchronizer inlined into surrounding logic cannot be annotated at all

## Coding Constraints

### General

- Keep a consistent, readable style throughout a file; no gate checks formatting
- No combinational feedback loops

### Port & Signal Declarations

- `wire` must be explicitly declared — no implicit `wire`
- Parameterized widths — no hardcoded magic-number widths (e.g., use `[DATA_W-1:0]` instead of `[31:0]`)

### Clock Signals

- **No** combinational clock generation or clock gating; clock gating must use dedicated ICG cells or be inserted by the synthesis tool
- Clock signals must not be used as combinational logic inputs or outputs (no clock-as-data)
- No implicit multi-drive within a single clock domain

### Reset Signals

- Polarity and kind are not yours to pick: `top-io.json` carries `reset_polarity` and
  `reset_kind` for every reset port, and that is the boundary you build to. Async active-low
  is the common case, not the required one
- Reset signals must not be used as combinational logic inputs/outputs; no combinational logic on async reset/set paths (prevents glitches)
- A register may use either async reset or async set, not both simultaneously

### `if-else` Statements

- Two `if`s in one block that can both reach the same signal are a priority you did not write
  down — say it with `if` / `else if`. Separate `if`s guarding separate signals are neither
  multi-drive nor ambiguous, and are how a register block is normally written
- An `if` / `else if` chain **is** a priority, so its order is behaviour. Reorder only
  conditions you already know to be mutually exclusive
- **Combinational logic** must have an `else` branch to prevent latch inference
- **Sequential logic** may omit `else` (register-hold semantics)
- No high-impedance (`z`/`Z`) in conditional expressions

### `case` Statements

- `case` is non-priority — use for mutually exclusive conditions; use `if-else` when priority is needed
- **Combinational logic** must have a `default` branch, or assign default values to all outputs at the top of the `always` block, to prevent latch inference
- **Sequential logic** may omit `default` (register-hold)
- No mixing of `x`/`z` masks in `casex`/`casez` (obscures design intent); make intent explicit with a `default` branch and mutually-exclusive conditions (`unique`/`priority` are SystemVerilog — not available in Verilog-2001)

### Loop Statements

- `for` loop iteration count must be a **constant** (parameter or `localparam`) — no dynamic loops
- `generate` blocks must have **named labels**: the label is what the elaborated hierarchy,
  the SDC and every report call the instance. A plain `for` inside an `always` names nothing
  and needs none

### Sequential Logic Template

Async active-low, the common case. Read the polarity and kind off `top-io.json` and write what
it says.

```verilog
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) <reg> <= <reset_val>;
    else        <reg> <= <next>;
end
```

### Tri-State Logic

- Tri-state enable must be controllable and logically determinate — no floating enables
- At most one driver may drive a tri-state bus at any time; internal tri-state buses must also ensure single-driver
- Prefer multiplexers (MUX) over internal tri-state buses

### FSM Coding

- **Separate combinational and sequential logic**: next-state logic (`always @*`) and the state register in separate blocks, the register written to the boundary's own reset polarity and kind
- Use `case` for state transitions; state encoding via `parameter`/`localparam` — no hardcoded numbers
- FSM must have a `default` branch pointing to a safe state (prevent runaway)
- Encoding is advisory, on the same terms as Low-Power Design below: Gray code for states that
  mostly step to their neighbour, one-hot/one-cold for small ones, fewer bits where neither
  applies — but never at the cost of behaviour `<child>.md §2` specifies
- Avoid redundant states; avoid high bit-flip counts between frequently transitioning states

### RAM Coding

- Register the RAM's control signals and its read/write addresses. The read data itself comes
  combinationally off the registered address — that is what a synchronous-read RAM is, and it
  is what a compiled macro gives you
- Read latency is one cycle; if additional latching exists on inputs/outputs, document the delay in comments
- Read/write addresses must not overflow; no simultaneous read/write conflict on the same address without explicit arbitration
- Data read out over multiple consecutive cycles must be registered first
- Encapsulate RAM models in a single file; ASIC RAM, FPGA RAM, and behavioral model in the same file, differentiated by macros (e.g., `` `ifdef SYNTHESIS ``)
- **Sizing.** Prefer single-port RAM (smaller area than dual-port); use dual-port only when genuinely needed. Above roughly 1024 bits dual-port or 16x32 bits single-port, use standard-cell RAM; below it, a register file. Merge fragmented small RAMs into larger blocks, and prefer high-density cells. These crossover numbers are a 65nm-class rule of thumb: the flow binds its actual library at deployment time through `LIB_DB`, so let the deployed library's own datasheet win where it disagrees

### Data Path

- Signed/unsigned operations must be explicitly declared and annotated; watch for sign extension and width alignment when mixing
- Add-then-multiply vs. multiply-then-add (MAC) differ in area/timing — choose per design requirements and comment the rationale
- Write large operators as operators and let synthesis infer them; `ppa.json`'s targets are
  what decides whether the inference was good enough. Naming a DesignWare component pins the
  design to one vendor's library, so reach for it only against a target you can point at
- Write RTL in a style friendly to synthesis tool data-path optimization (resource sharing, retiming)

## Comment Conventions

- Module header comment: module name + what the module does
- Port list: add group comments for each group (clock/reset/input/output)
- Critical logic, FSMs, CDC synchronizers, RAM access timing, etc. must have inline comments explaining design intent
- No meaningless comments (e.g., `// assign`, `// always`); comments must explain "why", not "what"

## Low-Power Design

**Advisory, this section and Low-Cost Design below.** No gate checks either one: `synthesis` and `power-analysis` only measure the outcome against `ppa.json`'s targets. So never trade away behavior your `<child>.md §2` specifies in order to satisfy one of these: a deviation from §2 intent is what the intent reviewer is looking for, while a missed power or area optimization is not.

- **Clock gating**: use module-level ICG; support automatic gating for sub-modules inside complex modules; minimize clock-gating cascade depth; RTL style must be friendly to synthesis tool auto-inference of clock gating
- **Memory**: gate clock, chip-select, and address for memories; encode address buses (e.g., Gray code) to reduce toggle power; bank large memories with high-bit address decode, shutting inactive banks; use the deployed library's low-power memory cells (FSM encoding and RAM sizing are covered under FSM Coding and RAM Coding above)
- **Operand isolation & early computation**: gate operands when not computing to prevent idle toggling; use early computation to pre-calculate and latch data, reducing redundant computation on critical paths; reduce logic depth of high-toggle signals; hold don't-care signals at their last value rather than forcing 0/1; use parallel structures and pipelining to lower frequency requirements

## Low-Cost Design

- Minimize total on-chip memory (SRAM/ROM), and consolidate scattered FIFOs and register groups into shared SRAMs rather than many small ones
- Minimize intermediate storage — use computation results immediately where possible
- Keep read/write arbitration clean, so no protection logic is needed to compensate for it

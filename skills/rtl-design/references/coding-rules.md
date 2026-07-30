# RTL coding rules

Applies to: `**/*.v` / `**/*.vh`

## General Constraints

- **Strict Verilog-2001 only — no SystemVerilog.** RTL files are `.v` (headers `.vh`), never `.sv`/`.svh`: the kernel's downstream `rtl` selectors match `*.v` alone, so a `.sv` file silently drops out of the dependency graph, and `rtl-files.schema.json` rejects the extension for exactly that reason. The **content** being V2001 is on you — no gate decides it, and the downstream tools would happily compile SystemVerilog. The common substitutions are types (`logic`/`bit`/`byte`/`int` → `wire`/`reg`/`integer`), always-blocks (`always_ff`/`always_comb`/`always_latch` → `always @(posedge …)` / `always @*`), and constructs with no V2001 equivalent at all (`typedef`/`enum`/`struct`/`union`/`interface`/`package`/`modport`/`import`/`unique`/`priority`) — a cheat sheet for the common cases, not a complete list of what the language forbids you. Do not use non-standard extensions unsupported by the toolchain
- Do not use Verilog/VHDL/SV reserved words as signal, module, or parameter names
- Code must be synthesizable: no `#delay`, `initial` blocks driving synthesizable logic, or simulation-only statements (`$display`, etc.) in synthesizable RTL

## Naming Conventions

- Clear and consistent naming; names should be self-explanatory; follow project-wide naming conventions (case, prefixes/suffixes)
- Distinguish signal direction and type: use uniform prefixes/suffixes for input/output, clock/reset, enable/data
- Parameters and macros: UPPER_CASE with underscores; local signals: lower_case with underscores

## Module Partitioning

- Single responsibility per module/interface; avoid deep nesting, break complex combinational logic into named intermediate signals
- Separate sequential and combinational logic clearly; avoid mixing unrelated logic in the same `always` block
- Header files (`*.vh`): centralize macros and parameters; avoid circular includes
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

- Default: asynchronous reset, active-low (`negedge rst_n`)
- Reset signals must not be used as combinational logic inputs/outputs; no combinational logic on async reset/set paths (prevents glitches)
- A register may use either async reset or async set, not both simultaneously

### `if-else` Statements

- **No** parallel `if` statements (use `if-else if-else` chains to express mutual exclusion); parallel `if` implies multi-drive or priority ambiguity
- `if-else if` chains have priority: place frequently-used or complex conditions first
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
- `generate/for` and regular `for` loop blocks must have **named labels**

### Sequential Logic Template

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

- **Separate combinational and sequential logic**: next-state logic (`always @*`) and state register (`always @(posedge clk or negedge rst_n)`) in separate blocks
- Use `case` for state transitions; state encoding via `parameter`/`localparam` — no hardcoded numbers
- FSM must have a `default` branch pointing to a safe state (prevent runaway)
- Low-power encoding: prefer Gray code for frequently transitioning adjacent states; one-hot/one-cold for small FSMs; minimize encoding bits
- Avoid redundant states; avoid high bit-flip counts between frequently transitioning states

### RAM Coding

- RAM input control signals, read/write addresses, and output data must be registered — avoid direct combinational drive
- Read latency is one cycle; if additional latching exists on inputs/outputs, document the delay in comments
- Read/write addresses must not overflow; no simultaneous read/write conflict on the same address without explicit arbitration
- Data read out over multiple consecutive cycles must be registered first
- Encapsulate RAM models in a single file; ASIC RAM, FPGA RAM, and behavioral model in the same file, differentiated by macros (e.g., `` `ifdef SYNTHESIS ``)
- **Sizing.** Prefer single-port RAM (smaller area than dual-port); use dual-port only when genuinely needed. Above roughly 1024 bits dual-port or 16x32 bits single-port, use standard-cell RAM; below it, a register file. Merge fragmented small RAMs into larger blocks, and prefer high-density cells. These crossover numbers are a 65nm-class rule of thumb: the flow binds its actual library at deployment time through `LIB_DB`, so let the deployed library's own datasheet win where it disagrees

### Data Path

- Signed/unsigned operations must be explicitly declared and annotated; watch for sign extension and width alignment when mixing
- Add-then-multiply vs. multiply-then-add (MAC) differ in area/timing — choose per design requirements and comment the rationale
- Multipliers, dividers, and other large operators must follow the project's cell library and constraints; no casual DesignWare (DW) component instantiation without project review
- Write RTL in a style friendly to synthesis tool data-path optimization (resource sharing, retiming)

## Comment Conventions

- Module header comment: module name + what the module does
- Port list: add group comments for each group (clock/reset/input/output)
- Critical logic, FSMs, CDC synchronizers, RAM access timing, etc. must have inline comments explaining design intent
- No meaningless comments (e.g., `// assign`, `// always`); comments must explain "why", not "what"

## Low-Power Design

**Advisory, this section and Low-Cost Design below.** No gate checks either one: `synthesis` and `power-analysis` only measure the outcome against the PPA targets. So never trade away behavior your `<child>.md §2` specifies in order to satisfy one of these: a deviation from §2 intent is what the intent reviewer is looking for, while a missed power or area optimization is not.

- **Clock gating**: use module-level ICG; support automatic gating for sub-modules inside complex modules; minimize clock-gating cascade depth; RTL style must be friendly to synthesis tool auto-inference of clock gating
- **Memory**: gate clock, chip-select, and address for memories; encode address buses (e.g., Gray code) to reduce toggle power; bank large memories with high-bit address decode, shutting inactive banks; use the deployed library's low-power memory cells (FSM encoding and RAM sizing are covered under FSM Coding and RAM Coding above)
- **Operand isolation & early computation**: gate operands when not computing to prevent idle toggling; use early computation to pre-calculate and latch data, reducing redundant computation on critical paths; reduce logic depth of high-toggle signals; hold don't-care signals at their last value rather than forcing 0/1; use parallel structures and pipelining to lower frequency requirements

## Low-Cost Design

- Minimize total on-chip memory (SRAM/ROM), and consolidate scattered FIFOs and register groups into shared SRAMs rather than many small ones
- Minimize intermediate storage — use computation results immediately where possible
- Keep read/write arbitration clean, so no protection logic is needed to compensate for it

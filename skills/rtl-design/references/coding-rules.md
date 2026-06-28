# RTL coding rules

Applies to: `**/*.sv` / `**/*.v` / `**/*.svh` / `**/*.vh`

## General Constraints

- Use Verilog-2001 syntax; do not use non-standard extensions unsupported by the toolchain
- Do not use Verilog/VHDL/SV reserved words as signal, module, or parameter names
- Code must be synthesizable: no `#delay`, `initial` blocks driving synthesizable logic, or simulation-only statements (`$display`, etc.) in synthesizable RTL

## Naming Conventions

- Clear and consistent naming; names should be self-explanatory; follow project-wide naming conventions (case, prefixes/suffixes)
- Distinguish signal direction and type: use uniform prefixes/suffixes for input/output, clock/reset, enable/data
- Parameters and macros: UPPER_CASE with underscores; local signals: lower_case with underscores
- No single-letter signal names (except loop variables in testbenches)

## Module Partitioning

- Single responsibility per module/interface; avoid deep nesting, break complex combinational logic into named intermediate signals
- Separate sequential and combinational logic clearly; avoid mixing unrelated logic in the same `always`/`always_ff` block
- Header files (`*.svh`/`*.vh`): centralize macros and parameters; avoid circular includes
- Cross-clock domain synchronizers, tri-state drivers, and other special structures must be encapsulated as separate modules/files

## Coding Constraints

### General

- One statement per line; explicit `begin...end` even for single statements
- No combinational feedback loops; multipliers/dividers and large operators must follow project cell library and constraints — do not casually instantiate DesignWare (DW)
- Signed/unsigned operations must be explicitly declared; watch for width and sign extension when mixing

### Port & Signal Declarations

- Each port/signal on its own line; align similar ports (width column, name column)
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
- No mixing of `x`/`z` masks in `casex`/`casez` (obscures design intent); prefer `unique case`/`priority case` (SV) for explicit semantics

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

- **Separate combinational and sequential logic**: next-state logic (`always_comb`/`always @*`) and state register (`always_ff`) in separate blocks
- Use `case` for state transitions; state encoding via `parameter`/`localparam` — no hardcoded numbers
- FSM must have a `default` branch pointing to a safe state (prevent runaway)
- Low-power: prefer Gray code for frequently transitioning states; one-hot/one-cold for small FSMs; minimize encoding bits
- Avoid redundant states; avoid high bit-flip counts between frequently transitioning states

### RAM Coding

- RAM input control signals, read/write addresses, and output data must be registered — avoid direct combinational drive
- Read latency is one cycle; if additional latching exists on inputs/outputs, document the delay in comments
- Read/write addresses must not overflow; no simultaneous read/write conflict on the same address without explicit arbitration
- Data read out over multiple consecutive cycles must be registered first
- Encapsulate RAM models in a single file; ASIC RAM, FPGA RAM, and behavioral model in the same file, differentiated by macros (e.g., `` `ifdef SYNTHESIS ``)
- Size guidelines (TSMC 65nm reference): dual-port RAM >= 1024 bits or single-port RAM >= 16x32 bits, use standard-cell RAM; smaller, use a register file. Avoid fragmented small RAMs; merge into larger blocks. Prefer single-port RAM for area/power

### Data Path

- Signed/unsigned operations must be explicitly declared and annotated; watch for sign extension and width alignment when mixing
- Add-then-multiply vs. multiply-then-add (MAC) differ in area/timing — choose per design requirements and comment the rationale
- No casual DesignWare (DW) component instantiation without project review
- Write RTL in a style friendly to synthesis tool data-path optimization (resource sharing, retiming)

## Comment Conventions

- Module header must have a file-header comment: module name, functional description, author, create/modify date, version
- Port list: add group comments for each group (clock/reset/input/output)
- Critical logic, FSMs, CDC synchronizers, RAM access timing, etc. must have inline comments explaining design intent
- No meaningless comments (e.g., `// assign`, `// always`); comments must explain "why", not "what"

## Low-Power Design

- **Clock gating**: use module-level ICG; support automatic gating for sub-modules inside complex modules; minimize clock-gating cascade depth; RTL style must be friendly to synthesis tool auto-inference of clock gating
- **Memory**: minimize memory size and unnecessary read/writes; gate clock, chip-select, and address for memories; encode address buses (e.g., Gray code) to reduce toggle power; bank large memories with high-bit address decode, shutting inactive banks; use low-power memory cells from project PDK
- **FSM**: Gray code for frequently switching adjacent states; minimize encoding bits; avoid redundant states and high-toggle transitions
- **Operand isolation & early computation**: gate operands when not computing to prevent idle toggling; use early computation to pre-calculate and latch data, reducing redundant computation on critical paths; reduce logic depth of high-toggle signals; hold don't-care signals at their last value rather than forcing 0/1; use parallel structures and pipelining to lower frequency requirements

## Low-Cost Design

- Minimize on-chip memory (SRAM/ROM) total; evaluate SRAM vs. register file for area/power
- Avoid fragmented SRAMs; use consolidated SRAMs instead of scattered FIFOs and register groups
- Use high-density memory (HD/UHD from project PDK)
- Minimize intermediate storage — use computation results immediately where possible
- Prefer **single-port RAM** (smaller area than dual-port); dual-port only when truly needed
- Clean read/write arbitration design — avoid unnecessary protection logic overhead

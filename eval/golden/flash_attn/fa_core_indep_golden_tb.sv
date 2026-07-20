// ============================================================================
// fa_core_indep — FIXED golden testbench (§1.3(a) functional gate).
//
// The independent, arm-neutral adjudication TB. It is NOT either arm's own TB
// (§1.3 symmetry / §5 no-self-eval): one fixed bench binds ANY implementation
// that conforms to the pinned top interface (asic/fa_core_indep/brainstorm.md,
// "Beat bit-packing & module identity") and scores its top-level `o_out` against
// the held-out golden vectors from reference.py — black-box, no internal probes.
//
// Gate: for EVERY tile (all held-out seeds × both causal modes), per-element
//   |err| < 1e-2  AND  mean|err| over the 16 O elements < 1e-3
// (err = decoded fp16 DUT output vs the fp32 reference). Any tile failing → FAIL.
//
// Inputs:  +VECTORS=<path>  token stream emitted by `reference.py --format tb`:
//            <N>
//            <causal_en> <12 beats %016x, Q,K,V rows 0-3> <16 expected reals row-major>
//            ...
// Output:  a single "GOLDEN: PASS|FAIL ..." marker line, plus a nonzero exit
//          ($fatal) on FAIL — so a --golden-cmd wrapper reads exit 0 == pass.
//
// STATUS: DRAFT — authored to the pinned interface but NOT yet compiled/run
// (needs a conforming DUT + VCS). fp16 decode + handshake sequencing are the
// two spots to re-verify against the first real DUT.
// ============================================================================
`timescale 1ns/1ps

module fa_core_indep_golden_tb;

  // ---- fixed interface (pinned in the spec) --------------------------------
  logic        clk;
  logic        rst_n;
  logic [63:0] qkv_in_data;
  logic        qkv_in_valid;
  logic        qkv_in_ready;
  logic        causal_en;
  logic [63:0] o_out_data;
  logic        o_out_valid;
  logic        o_out_ready;
  logic        busy;
  logic        done;

  fa_core_indep dut (
    .clk          (clk),
    .rst_n        (rst_n),
    .qkv_in_data  (qkv_in_data),
    .qkv_in_valid (qkv_in_valid),
    .qkv_in_ready (qkv_in_ready),
    .causal_en    (causal_en),
    .o_out_data   (o_out_data),
    .o_out_valid  (o_out_valid),
    .o_out_ready  (o_out_ready),
    .busy         (busy),
    .done         (done)
  );

  // ---- clock (10 ns) + async active-low reset ------------------------------
  initial clk = 1'b0;
  always #5 clk = ~clk;

  // ---- global watchdog: no response ⇒ FAIL (never a false pass) -------------
  initial begin
    #1_000_000;                       // 100k cycles ≫ 10 tiles × ~76 cyc
    $display("GOLDEN: FAIL timeout");
    $fatal(1, "golden timeout");
  end

  // ---- fp16 (E5M10) → real, for decoding the DUT's o_out lanes -------------
  function automatic real fp16_to_real(input logic [15:0] h);
    logic       sign;
    int         ex;
    int         ma;
    real        val;
    begin
      sign = h[15];
      ex   = int'(h[14:10]);
      ma   = int'(h[9:0]);
      if (ex == 0)
        val = $itor(ma) * (2.0 ** (-24.0));                 // zero / subnormal
      else if (ex == 31)
        val = 1.0e30;                                       // inf/nan (unexpected)
      else
        val = (1.0 + $itor(ma) * (2.0 ** (-10.0)))
              * (2.0 ** ($itor(ex) - 15.0));
      fp16_to_real = sign ? -val : val;
    end
  endfunction

  // ---- drive one input beat under valid/ready (blocking) -------------------
  task automatic send_beat(input logic [63:0] d);
    begin
      qkv_in_data  <= d;
      qkv_in_valid <= 1'b1;
      do @(posedge clk); while (!qkv_in_ready);            // accepted this edge
    end
  endtask

  // ---- run one tile: 12 in beats → 4 out beats → tolerance check -----------
  int    n_fail;
  int    n_tiles;

  task automatic run_tile(input int t,
                          input logic       cz,
                          input logic [63:0] beats [0:11],
                          input real         exp_o  [0:15]);
    logic [63:0] cap [0:3];
    real got, want, err, maxerr, sumerr, mae;
    int  r, c, b;
    begin
      // causal_en is latched at the first accepted beat — present it first.
      causal_en <= cz;
      for (b = 0; b < 12; b++) send_beat(beats[b]);
      qkv_in_valid <= 1'b0;

      // drain 4 output rows (continuous ready; no backpressure in the golden).
      for (r = 0; r < 4; r++) begin
        do @(posedge clk); while (!o_out_valid);
        cap[r] = o_out_data;
      end

      // let the tile finish (done pulse / busy fall) before the next one.
      while (busy) @(posedge clk);

      maxerr = 0.0; sumerr = 0.0;
      for (r = 0; r < 4; r++)
        for (c = 0; c < 4; c++) begin
          got  = fp16_to_real(cap[r][16*c +: 16]);
          want = exp_o[r*4 + c];
          err  = (got > want) ? (got - want) : (want - got);
          if (err > maxerr) maxerr = err;
          sumerr = sumerr + err;
        end
      mae = sumerr / 16.0;

      n_tiles++;
      if (!((maxerr < 1.0e-2) && (mae < 1.0e-3))) begin
        n_fail++;
        $display("GOLDEN: tile %0d (causal=%0b) FAIL  maxerr=%g mae=%g",
                 t, cz, maxerr, mae);
      end
    end
  endtask

  // ---- vector load + sequencing --------------------------------------------
  string       vecfile;
  int          fd, code, nvec, t, b, k;
  logic        cz;
  logic [63:0] beats [0:11];
  real         exp_o [0:15];

  initial begin
    n_fail = 0; n_tiles = 0;
    qkv_in_data = '0; qkv_in_valid = 1'b0; causal_en = 1'b0; o_out_ready = 1'b1;

    // async active-low reset for a few cycles.
    rst_n = 1'b0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    @(posedge clk);

    if (!$value$plusargs("VECTORS=%s", vecfile)) begin
      $display("GOLDEN: FAIL no +VECTORS=<file>");
      $fatal(1, "no vectors");
    end
    fd = $fopen(vecfile, "r");
    if (fd == 0) begin
      $display("GOLDEN: FAIL cannot open %s", vecfile);
      $fatal(1, "fopen");
    end

    code = $fscanf(fd, "%d", nvec);
    if (code != 1) begin
      $display("GOLDEN: FAIL bad vector header");
      $fatal(1, "header");
    end

    for (t = 0; t < nvec; t++) begin
      code = $fscanf(fd, "%d", cz);
      for (b = 0; b < 12; b++) code = $fscanf(fd, "%h", beats[b]);
      for (k = 0; k < 16; k++) code = $fscanf(fd, "%g", exp_o[k]);
      run_tile(t, cz, beats, exp_o);
    end
    $fclose(fd);

    if (n_fail == 0) begin
      $display("GOLDEN: PASS (%0d tiles)", n_tiles);
      $finish;
    end else begin
      $display("GOLDEN: FAIL (%0d/%0d tiles)", n_fail, n_tiles);
      $fatal(1, "golden tolerance");
    end
  end

endmodule

// F1 regression DUT: a genuine async crossing (a: clk domain -> q: clk2 domain)
// with NO synchronizer. SpyGlass CDC must flag it iff clk/clk2 are declared async.
module cdc_smoke (
    input  wire clk,
    input  wire clk2,
    input  wire rst_n,
    input  wire d,
    output reg  q
);
    reg a;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) a <= 1'b0;
        else        a <= d;

    // Unsynchronized single-FF sample of `a` (clk domain) by clk2 — a CDC violation
    // exactly when clk and clk2 are asynchronous.
    always @(posedge clk2 or negedge rst_n)
        if (!rst_n) q <= 1'b0;
        else        q <= a;
endmodule

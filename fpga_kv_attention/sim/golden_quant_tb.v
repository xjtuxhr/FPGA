`timescale 1ns/1ps
// ============================================================================
// golden_quant_tb.v —— kv_quant 软硬件对拍 testbench
// 读 golden/quant.hex（每行 64-bit），逐条喂给 kv_quant，比对 q。
// ============================================================================
module golden_quant_tb;

    parameter N = 2000;

    reg [63:0] vec [0:N-1];
    reg clk = 0, rst_n = 0, valid_in = 0;
    reg signed [15:0] x = 0;
    reg signed [15:0] min = 0;
    reg [15:0] inv_scale = 0;
    wire valid_out;
    wire [3:0] q;

    kv_quant #(.Q_BITS(4), .X_W(16), .INV_W(16))
        dut (.clk(clk), .rst_n(rst_n), .valid_in(valid_in),
             .x(x), .min(min), .inv_scale(inv_scale),
             .valid_out(valid_out), .q(q));

    always #5 clk = ~clk;

    integer i, errors = 0;

    initial begin
        $readmemh("golden/quant.hex", vec);
        #20 rst_n = 1'b1; #10;
        for (i = 0; i < N; i = i + 1) begin
            @(negedge clk);
            valid_in  <= 1'b1;
            x         <= vec[i][15:0];
            min       <= vec[i][31:16];
            inv_scale <= vec[i][47:32];
            @(negedge clk);
            valid_in <= 1'b0;
            if (q !== vec[i][51:48]) begin
                errors = errors + 1;
                if (errors <= 10)
                    $display("FAIL i=%0d: x=%0d min=%0d inv=%0d -> q=%0d exp=%0d",
                             i, $signed(vec[i][15:0]), $signed(vec[i][31:16]),
                             vec[i][47:32], q, vec[i][51:48]);
            end
        end
        #20;
        if (errors == 0) $display("golden_quant: ALL %0d PASSED", N);
        else $display("golden_quant: %0d ERRORS / %0d", errors, N);
        $finish;
    end

endmodule

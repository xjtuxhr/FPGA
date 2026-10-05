`timescale 1ns/1ps
// ============================================================================
// golden_dequant_tb.v —— kv_dequant 软硬件对拍 testbench
// 读 golden/dequant.hex（每行 64-bit），逐条喂给 kv_dequant，比对 x。
// ============================================================================
module golden_dequant_tb;

    parameter N = 2000;

    reg [63:0] vec [0:N-1];
    reg clk = 0, rst_n = 0, valid_in = 0;
    reg [3:0] q = 0;
    reg [15:0] scale = 0;
    reg signed [15:0] min = 0;
    wire valid_out;
    wire signed [15:0] x;

    kv_dequant #(.Q_BITS(4), .SCALE_W(16), .MIN_W(16), .OUT_W(16))
        dut (.clk(clk), .rst_n(rst_n), .valid_in(valid_in),
             .q(q), .scale(scale), .min(min),
             .valid_out(valid_out), .x(x));

    always #5 clk = ~clk;

    integer i, errors = 0;

    initial begin
        $readmemh("golden/dequant.hex", vec);
        #20 rst_n = 1'b1; #10;
        for (i = 0; i < N; i = i + 1) begin
            @(negedge clk);
            valid_in <= 1'b1;
            q     <= vec[i][3:0];
            scale <= vec[i][19:4];
            min   <= vec[i][35:20];
            @(negedge clk);
            valid_in <= 1'b0;
            if (x !== $signed(vec[i][51:36])) begin
                errors = errors + 1;
                if (errors <= 10)
                    $display("FAIL i=%0d: q=%0d scale=%0d min=%0d -> x=%0d exp=%0d",
                             i, vec[i][3:0], vec[i][19:4], $signed(vec[i][35:20]),
                             x, $signed(vec[i][51:36]));
            end
        end
        #20;
        if (errors == 0) $display("golden_dequant: ALL %0d PASSED", N);
        else $display("golden_dequant: %0d ERRORS / %0d", errors, N);
        $finish;
    end

endmodule

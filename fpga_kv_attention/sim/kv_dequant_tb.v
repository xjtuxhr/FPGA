`timescale 1ns/1ps
// ============================================================================
// kv_dequant_tb.v —— kv_dequant 自校验 testbench
//
// 运行：iverilog -o tb.vvp kv_dequant.v kv_dequant_tb.v && vvp tb.vvp
//       （或用 TD 自带的仿真器）
// ============================================================================
module kv_dequant_tb;

    parameter Q_BITS  = 4;
    parameter SCALE_W = 16;
    parameter MIN_W   = 16;
    parameter OUT_W   = 16;

    reg clk = 0;
    reg rst_n = 0;
    reg valid_in = 0;
    reg [Q_BITS-1:0]  q = 0;
    reg [SCALE_W-1:0] scale = 0;
    reg signed [MIN_W-1:0] min = 0;

    wire valid_out;
    wire signed [OUT_W-1:0] x;

    kv_dequant #(.Q_BITS(Q_BITS), .SCALE_W(SCALE_W), .MIN_W(MIN_W), .OUT_W(OUT_W))
        dut (.clk(clk), .rst_n(rst_n), .valid_in(valid_in),
             .q(q), .scale(scale), .min(min),
             .valid_out(valid_out), .x(x));

    always #5 clk = ~clk;   // 100 MHz

    integer errors = 0;

    // 应用一组输入，一拍后检查输出（x = q*scale + min，Q8.8 定点）
    task check;
        input [Q_BITS-1:0]  tq;
        input [SCALE_W-1:0] tscale;
        input signed [MIN_W-1:0] tmin;
        input signed [OUT_W-1:0] expected;
        begin
            @(negedge clk);
            valid_in <= 1'b1;
            q <= tq; scale <= tscale; min <= tmin;
            @(negedge clk);
            valid_in <= 1'b0;
            if (x !== expected) begin
                errors = errors + 1;
                $display("FAIL: q=%0d scale=%0d min=%0d -> x=%0d (expected %0d)",
                         tq, tscale, tmin, x, expected);
            end else begin
                $display("PASS: q=%0d scale=%0d min=%0d -> x=%0d",
                         tq, tscale, tmin, x);
            end
        end
    endtask

    initial begin
        #20 rst_n = 1'b1;
        #10;
        // 手工算好的向量（scale Q0.8，min/x Q8.8）：
        check(4'd3,  16'd256,   16'sd0,     16'sd768);   // 3*1.0 + 0    = 3.0
        check(4'd2,  16'd128,   16'sd256,   16'sd512);   // 2*0.5 + 1.0  = 2.0
        check(4'd15, 16'd256,  -16'sd256,   16'sd3584);  // 15*1.0 - 1.0 = 14.0
        check(4'd0,  16'd100,   16'sd50,    16'sd50);    // 0*0.39 + 0.195 = 0.195
        check(4'd7,  16'd0,     16'sd0,     16'sd0);     // scale=0 边界

        #20;
        if (errors == 0)
            $display("ALL PASSED");
        else
            $display("%0d ERRORS", errors);
        $finish;
    end

endmodule

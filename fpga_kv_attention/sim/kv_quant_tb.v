`timescale 1ns/1ps
// ============================================================================
// kv_quant_tb.v —— kv_quant 自校验 testbench
//
// 验证：q = clamp(round((x-min)*inv_scale), 0, QMAX)
//   定点格式：x/min Q8.8 有符号，inv_scale Q8.8 无符号
//   覆盖：普通量化、四舍五入(half up)、上截位、下截位、(x-min)=0 边界
// ============================================================================
module kv_quant_tb;

    parameter Q_BITS = 4;
    parameter X_W    = 16;
    parameter INV_W  = 16;

    reg clk = 0, rst_n = 0, valid_in = 0;
    reg signed [X_W-1:0] x = 0;
    reg signed [X_W-1:0] min = 0;
    reg [INV_W-1:0] inv_scale = 0;

    wire valid_out;
    wire [Q_BITS-1:0] q;

    kv_quant #(.Q_BITS(Q_BITS), .X_W(X_W), .INV_W(INV_W))
        dut (.clk(clk), .rst_n(rst_n), .valid_in(valid_in),
             .x(x), .min(min), .inv_scale(inv_scale),
             .valid_out(valid_out), .q(q));

    always #5 clk = ~clk;

    integer errors = 0;

    task check;
        input signed [X_W-1:0] tx;
        input signed [X_W-1:0] tmin;
        input [INV_W-1:0] tinv;
        input [Q_BITS-1:0] expected;
        begin
            @(negedge clk);
            valid_in <= 1'b1;
            x <= tx; min <= tmin; inv_scale <= tinv;
            @(negedge clk);
            valid_in <= 1'b0;
            if (q !== expected) begin
                errors = errors + 1;
                $display("FAIL: x=%0d min=%0d inv=%0d -> q=%0d (expected %0d)",
                         tx, tmin, tinv, q, expected);
            end else begin
                $display("PASS: x=%0d min=%0d inv=%0d -> q=%0d", tx, tmin, tinv, q);
            end
        end
    endtask

    initial begin
        #20 rst_n = 1'b1; #10;
        // x/min 为 Q8.8（值 = int/256），inv_scale 为 Q8.8（值 = int/256）
        check( 16'sd512,    16'sd0,   16'd256, 4'd2 );   // round(2.0) = 2
        check( 16'sd0,      16'sd0,   16'd256, 4'd0 );   // 0
        check( 16'sd384,    16'sd0,   16'd256, 4'd2 );   // round(1.5) = 2（half up）
        check(-16'sd256,   -16'sd256, 16'd256, 4'd0 );   // (x-min)=0 -> 0
        check( 16'sd4096,   16'sd0,   16'd256, 4'd15);   // 16.0 上截位 -> 15
        check(-16'sd512,    16'sd0,   16'd256, 4'd0 );   // -2.0 下截位 -> 0

        #20;
        if (errors == 0) $display("ALL PASSED"); else $display("%0d ERRORS", errors);
        $finish;
    end

endmodule

`timescale 1ns/1ps
// ============================================================================
// round_trip_tb.v —— kv_quant + kv_dequant 串联自校验 testbench
//
// 验证整条量化链路：x -> 量化得 q -> 反量化得 x_recon，
//   检查 q 正确、且 x_recon 落在 [min, max] 内、误差不超过一个量化步长。
//
// 本组测试固定：min = -5.0（-1280）、max = 10.0（2560）、qmax=15，
//   于是 scale = 1.0（256）、inv_scale = 1.0（256），方便手算。
// ============================================================================
module round_trip_tb;

    parameter Q_BITS  = 4;
    parameter X_W     = 16;
    parameter SCALE_W = 16;
    parameter MIN_W   = 16;
    parameter INV_W   = 16;
    parameter OUT_W   = 16;

    reg clk = 0, rst_n = 0;
    reg q_valid = 0;
    reg signed [X_W-1:0] x = 0;
    reg signed [X_W-1:0] min = 0;
    reg [INV_W-1:0] inv_scale = 0;
    reg [SCALE_W-1:0] scale = 0;
    reg dq_valid = 0;

    wire [Q_BITS-1:0] q;
    wire q_valid_out;
    wire signed [OUT_W-1:0] x_recon;
    wire dq_valid_out;

    kv_quant #(.Q_BITS(Q_BITS), .X_W(X_W), .INV_W(INV_W))
        u_quant (.clk(clk), .rst_n(rst_n), .valid_in(q_valid),
                 .x(x), .min(min), .inv_scale(inv_scale),
                 .valid_out(q_valid_out), .q(q));

    kv_dequant #(.Q_BITS(Q_BITS), .SCALE_W(SCALE_W), .MIN_W(MIN_W), .OUT_W(OUT_W))
        u_dequant (.clk(clk), .rst_n(rst_n), .valid_in(dq_valid),
                   .q(q), .scale(scale), .min(min),
                   .valid_out(dq_valid_out), .x(x_recon));

    always #5 clk = ~clk;

    integer errors = 0;

    // 串联：喂 x（量化一拍）-> 送 q（反量化一拍）-> 检查 q 和 x_recon
    task round_trip;
        input signed [X_W-1:0] tx;
        input signed [X_W-1:0] tmin;
        input [INV_W-1:0] tinv;
        input [SCALE_W-1:0] tscale;
        input [Q_BITS-1:0] expected_q;
        input signed [OUT_W-1:0] expected_x;
        begin
            @(negedge clk);
            q_valid <= 1'b1;
            x <= tx; min <= tmin; inv_scale <= tinv; scale <= tscale;
            @(negedge clk);      // q 已就绪
            q_valid <= 1'b0;
            dq_valid <= 1'b1;
            @(negedge clk);      // x_recon 已就绪
            dq_valid <= 1'b0;
            if (q !== expected_q || x_recon !== expected_x) begin
                errors = errors + 1;
                $display("FAIL: x=%0d -> q=%0d(exp %0d), x_recon=%0d(exp %0d)",
                         tx, q, expected_q, x_recon, expected_x);
            end else begin
                $display("PASS: x=%0d -> q=%0d, x_recon=%0d", tx, q, x_recon);
            end
        end
    endtask

    initial begin
        #20 rst_n = 1'b1; #10;
        // min=-5.0(-1280), scale=inv_scale=1.0(256)
        round_trip(-16'sd1280, -16'sd1280, 16'd256, 16'd256, 4'd0,  -16'sd1280); // -5 -> q=0, xr=-5
        round_trip( 16'sd0,    -16'sd1280, 16'd256, 16'd256, 4'd5,   16'sd0);    // 0  -> q=5, xr=0
        round_trip( 16'sd2560, -16'sd1280, 16'd256, 16'd256, 4'd15,  16'sd2560); // 10 -> q=15, xr=10
        round_trip( 16'sd640,  -16'sd1280, 16'd256, 16'd256, 4'd8,   16'sd768);  // 2.5 -> q=8, xr=3（舍入）

        #20;
        if (errors == 0) $display("ALL PASSED"); else $display("%0d ERRORS", errors);
        $finish;
    end

endmodule

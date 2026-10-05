`timescale 1ns/1ps
// weighted_sum_tb.v —— 加权求和自校验
// T=3, D=4：p=[2,3,4], v[t] 三行，期望 out = [53,62,71,80]
module weighted_sum_tb;
    parameter T = 3, D = 4, P_W = 16, V_W = 16;
    reg clk = 0, rst_n = 0, start = 0, p_valid = 0, v_valid = 0;
    reg [15:0] p = 0;
    reg signed [15:0] v = 0;
    wire out_valid;
    wire signed [31:0] out;
    wire [6:0] out_idx;

    weighted_sum #(.T(T), .D(D), .P_W(P_W), .V_W(V_W))
        dut (.clk(clk), .rst_n(rst_n), .start(start),
             .p_valid(p_valid), .p(p), .v_valid(v_valid), .v(v),
             .out_valid(out_valid), .out(out), .out_idx(out_idx));

    always #5 clk = ~clk;

    integer t, d, i, errors = 0;
    reg [15:0] pv [0:2];
    reg signed [15:0] vv [0:2][0:3];
    reg signed [31:0] expect [0:3];

    initial begin
        pv[0]=2; pv[1]=3; pv[2]=4;
        vv[0][0]=1; vv[0][1]=2; vv[0][2]=3; vv[0][3]=4;
        vv[1][0]=5; vv[1][1]=6; vv[1][2]=7; vv[1][3]=8;
        vv[2][0]=9; vv[2][1]=10; vv[2][2]=11; vv[2][3]=12;
        expect[0]=53; expect[1]=62; expect[2]=71; expect[3]=80;

        #20 rst_n = 1'b1; #10;

        // start 复位
        @(negedge clk); start <= 1'b1;
        @(negedge clk); start <= 1'b0;

        // 3 个 token：p 一拍，v 连续 D 拍
        for (t = 0; t < T; t = t + 1) begin
            @(negedge clk); p_valid <= 1'b1; p <= pv[t];
            @(negedge clk); p_valid <= 1'b0;
            for (d = 0; d < D; d = d + 1) begin
                @(negedge clk); v_valid <= 1'b1; v <= vv[t][d];
            end
            @(negedge clk); v_valid <= 1'b0;
        end

        // 等 emit，检查 D 个输出
        for (i = 0; i < D; i = i + 1) begin
            wait (out_valid == 1'b1);
            @(negedge clk);
            if (out !== expect[i] || out_idx !== i) begin
                errors = errors + 1;
                $display("FAIL: out[%0d]=%0d (expect %0d)", out_idx, out, expect[i]);
            end else $display("PASS: out[%0d]=%0d", out_idx, out);
        end

        #20;
        if (errors == 0) $display("ALL PASSED"); else $display("%0d ERRORS", errors);
        $finish;
    end
endmodule

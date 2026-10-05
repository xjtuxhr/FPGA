`timescale 1ns/1ps
// ============================================================================
// min_max_reduce_tb.v —— 自校验 testbench
// 喂入一组 32 个值 [0, 1, ..., 31]，期望 min=0、max=31
// ============================================================================
module min_max_reduce_tb;

    parameter DATA_W = 16;
    parameter GROUP_SIZE = 32;

    reg clk = 0;
    reg rst_n = 0;
    reg valid_in = 0;
    reg signed [DATA_W-1:0] value = 0;

    wire group_done;
    wire signed [DATA_W-1:0] min_out, max_out;

    min_max_reduce #(.DATA_W(DATA_W), .GROUP_SIZE(GROUP_SIZE))
        dut (.clk(clk), .rst_n(rst_n), .valid_in(valid_in), .value(value),
             .group_done(group_done), .min_out(min_out), .max_out(max_out));

    always #5 clk = ~clk;

    integer i;
    integer errors = 0;

    initial begin
        #20 rst_n = 1'b1;
        #10;

        // 喂入 0..31
        for (i = 0; i < GROUP_SIZE; i = i + 1) begin
            @(negedge clk);
            valid_in <= 1'b1;
            value <= i;
        end
        @(negedge clk);
        valid_in <= 1'b0;

        // 等组结束脉冲
        wait (group_done == 1'b1);
        @(negedge clk);
        if (min_out !== 0 || max_out !== 31) begin
            errors = errors + 1;
            $display("FAIL: min=%0d max=%0d (expected min=0 max=31)", min_out, max_out);
        end else begin
            $display("PASS: min=%0d max=%0d", min_out, max_out);
        end

        // 第二组：[-5, 10, -3, 7, ...] 用固定值验证负数和混合
        value = -5; valid_in = 1; @(negedge clk);
        value = 10; @(negedge clk);
        value = -3; @(negedge clk);
        value =  7; @(negedge clk);
        // 补齐到 32 个（随便填 0）
        for (i = 4; i < GROUP_SIZE; i = i + 1) begin
            value = 0; @(negedge clk);
        end
        valid_in <= 1'b0;
        wait (group_done == 1'b1);
        @(negedge clk);
        if (min_out !== -5 || max_out !== 10) begin
            errors = errors + 1;
            $display("FAIL: group2 min=%0d max=%0d (expected min=-5 max=10)", min_out, max_out);
        end else begin
            $display("PASS: group2 min=%0d max=%0d", min_out, max_out);
        end

        #20;
        if (errors == 0) $display("ALL PASSED"); else $display("%0d ERRORS", errors);
        $finish;
    end

endmodule

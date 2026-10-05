`timescale 1ns/1ps
// attention_tb.v —— attention 集成模块自校验
// 读 golden/attention.hex：Q(D) + K(T×D) + V(T×D) + out(D×2)
module attention_tb;
    parameter T = 4, D = 4, DATA_W = 16;

    reg [15:0] vec [0:D + T*D + T*D + D*2 - 1];
    reg clk = 0, rst_n = 0, start = 0;
    reg q_valid = 0, k_valid = 0, v_valid = 0;
    reg signed [15:0] q_in = 0, k_in = 0, v_in = 0;
    wire out_valid;
    wire signed [31:0] out;

    attention #(.T(T), .D(D), .DATA_W(DATA_W))
        dut (.clk(clk), .rst_n(rst_n), .start(start),
             .q_valid(q_valid), .q_in(q_in),
             .k_valid(k_valid), .k_in(k_in),
             .v_valid(v_valid), .v_in(v_in),
             .out_valid(out_valid), .out(out));

    always #5 clk = ~clk;

    integer i, t, d, errors = 0;
    reg signed [31:0] expect [0:D-1];

    initial begin
        $readmemh("golden/attention.hex", vec);
        for (d = 0; d < D; d = d + 1)
            expect[d] = {vec[D+T*D+T*D + 2*d], vec[D+T*D+T*D + 2*d + 1]};

        #20 rst_n = 1'b1; #10;

        // start
        @(negedge clk); start <= 1'b1;
        @(negedge clk); start <= 1'b0;

        // 喂 Q（D 个）
        for (d = 0; d < D; d = d + 1) begin
            @(negedge clk); q_valid <= 1'b1; q_in <= vec[d];
        end
        @(negedge clk); q_valid <= 1'b0;

        // 喂 K（T×D 个）
        for (i = 0; i < T*D; i = i + 1) begin
            @(negedge clk); k_valid <= 1'b1; k_in <= vec[D + i];
        end
        @(negedge clk); k_valid <= 1'b0;

        // 喂 V（T×D 个）
        for (i = 0; i < T*D; i = i + 1) begin
            @(negedge clk); v_valid <= 1'b1; v_in <= vec[D + T*D + i];
        end
        @(negedge clk); v_valid <= 1'b0;

        // 收 D 个 out
        for (d = 0; d < D; d = d + 1) begin
            @(posedge out_valid);
            @(negedge clk);
            if (out !== expect[d]) begin
                errors = errors + 1;
                $display("FAIL out[%0d]: %0d (expect %0d)", d, out, expect[d]);
            end else $display("PASS out[%0d]: %0d", d, out);
        end

        #20;
        if (errors == 0) $display("attention: ALL PASSED");
        else $display("attention: %0d ERRORS", errors);
        $finish;
    end
endmodule

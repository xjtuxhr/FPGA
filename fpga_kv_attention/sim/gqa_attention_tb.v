`timescale 1ns/1ps
// gqa_attention_tb.v —— GQA 头复用模块自校验
// 读 golden/gqa.hex：Q(H×D) + K(G×T×D) + V(G×T×D) + out(H×D×2)
module gqa_attention_tb;
    parameter H = 4, G = 2, D = 4, T = 4, DATA_W = 16;

    reg [15:0] vec [0:H*D + G*T*D + G*T*D + H*D*2 - 1];
    reg clk = 0, rst_n = 0, start = 0;
    reg q_valid = 0, k_valid = 0, v_valid = 0;
    reg signed [15:0] q_in = 0, k_in = 0, v_in = 0;
    wire out_valid;
    wire signed [31:0] out;
    wire [7:0] out_head, out_d;

    gqa_attention #(.H(H), .G(G), .D(D), .T(T), .DATA_W(DATA_W))
        dut (.clk(clk), .rst_n(rst_n), .start(start),
             .q_valid(q_valid), .q_in(q_in),
             .k_valid(k_valid), .k_in(k_in),
             .v_valid(v_valid), .v_in(v_in),
             .out_valid(out_valid), .out(out), .out_head(out_head), .out_d(out_d));

    always #5 clk = ~clk;

    integer i, h, d, errors = 0;
    reg signed [31:0] expect [0:H*D-1];

    initial begin
        $readmemh("golden/gqa.hex", vec);
        for (i = 0; i < H*D; i = i + 1)
            expect[i] = {vec[H*D + G*T*D + G*T*D + 2*i], vec[H*D + G*T*D + G*T*D + 2*i + 1]};

        #20 rst_n = 1'b1; #10;

        @(negedge clk); start <= 1'b1;
        @(negedge clk); start <= 1'b0;

        // 喂 Q
        for (i = 0; i < H*D; i = i + 1) begin
            @(negedge clk); q_valid <= 1'b1; q_in <= vec[i];
        end
        @(negedge clk); q_valid <= 1'b0;

        // 喂 K
        for (i = 0; i < G*T*D; i = i + 1) begin
            @(negedge clk); k_valid <= 1'b1; k_in <= vec[H*D + i];
        end
        @(negedge clk); k_valid <= 1'b0;

        // 喂 V
        for (i = 0; i < G*T*D; i = i + 1) begin
            @(negedge clk); v_valid <= 1'b1; v_in <= vec[H*D + G*T*D + i];
        end
        @(negedge clk); v_valid <= 1'b0;

        // 收 H×D 个输出
        for (i = 0; i < H*D; i = i + 1) begin
            @(posedge out_valid);
            @(negedge clk);
            if (out !== expect[i] || out_head !== (i / D) || out_d !== (i % D)) begin
                errors = errors + 1;
                $display("FAIL out[%0d][%0d]: %0d (expect %0d, head=%0d d=%0d)",
                         out_head, out_d, out, expect[i], i/D, i%D);
            end
        end

        #20;
        if (errors == 0) $display("gqa_attention: ALL %0d outputs PASSED", H*D);
        else $display("gqa_attention: %0d ERRORS", errors);
        $finish;
    end
endmodule

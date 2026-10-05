`timescale 1ns/1ps
// attention_b_tb.v —— Attention-only B 端到端自校验
// 读 golden/attention_b.hex：Q_fp16(H×D) + K_fp16(G×T×D) + V_fp16(G×T×D) + out(H×D×2)
module attention_b_tb;
    parameter H = 9, G = 3, D = 64, T = 64, DATA_W = 16;
    localparam VEC_SZ = H*D + G*T*D + G*T*D + H*D*2;

    reg [15:0] vec [0:VEC_SZ-1];
    reg clk = 0, rst_n = 0, start = 0;
    reg q_valid = 0, k_valid = 0, v_valid = 0;
    reg [15:0] q_fp16 = 0, k_fp16 = 0, v_fp16 = 0;
    wire out_valid;
    wire signed [31:0] out;
    wire [7:0] out_head, out_d;

    attention_b_top #(.H(H), .G(G), .D(D), .T(T), .DATA_W(DATA_W))
        dut (.clk(clk), .rst_n(rst_n), .start(start),
             .q_valid(q_valid), .q_fp16(q_fp16),
             .k_valid(k_valid), .k_fp16(k_fp16),
             .v_valid(v_valid), .v_fp16(v_fp16),
             .out_valid(out_valid), .out(out), .out_head(out_head), .out_d(out_d));

    always #5 clk = ~clk;

    integer i, errors = 0;
    reg signed [31:0] expect [0:H*D-1];

    initial begin
        $readmemh("golden/attention_b.hex", vec);
        for (i = 0; i < H*D; i = i + 1)
            expect[i] = {vec[H*D + G*T*D + G*T*D + 2*i],
                         vec[H*D + G*T*D + G*T*D + 2*i + 1]};

        #20 rst_n = 1'b1; #10;

        @(negedge clk); start <= 1'b1;
        @(negedge clk); start <= 1'b0;

        // Q（FP16，H×D）
        for (i = 0; i < H*D; i = i + 1) begin
            @(negedge clk); q_valid <= 1'b1; q_fp16 <= vec[i];
        end
        @(negedge clk); q_valid <= 1'b0;

        // K（FP16，G×T×D）
        for (i = 0; i < G*T*D; i = i + 1) begin
            @(negedge clk); k_valid <= 1'b1; k_fp16 <= vec[H*D + i];
        end
        @(negedge clk); k_valid <= 1'b0;

        // V（FP16，G×T×D）
        for (i = 0; i < G*T*D; i = i + 1) begin
            @(negedge clk); v_valid <= 1'b1; v_fp16 <= vec[H*D + G*T*D + i];
        end
        @(negedge clk); v_valid <= 1'b0;

        // 收 H×D 个输出
        for (i = 0; i < H*D; i = i + 1) begin
            @(posedge out_valid);
            @(negedge clk);
            if (out !== expect[i] || out_head !== (i / D) || out_d !== (i % D)) begin
                errors = errors + 1;
                if (errors <= 20)
                    $display("FAIL out[%0d][%0d]=%0d (expect %0d)",
                             out_head, out_d, out, expect[i]);
            end
        end

        #20;
        if (errors == 0) $display("attention_b: ALL %0d outputs PASSED", H*D);
        else $display("attention_b: %0d ERRORS", errors);
        $finish;
    end
endmodule

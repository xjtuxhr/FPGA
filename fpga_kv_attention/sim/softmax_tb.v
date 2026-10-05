`timescale 1ns/1ps
// softmax_tb.v —— softmax 软硬件对拍 testbench
// 读 golden/softmax.hex，逐 case 喂 score，比对输出 p。
module softmax_tb;
    parameter T = 4, N_CASES = 8;

    reg [15:0] vec [0:N_CASES*2*T-1];
    reg clk = 0, rst_n = 0, start = 0, valid_in = 0;
    reg signed [15:0] score = 0;
    wire valid_out;
    wire [15:0] prob;

    softmax #(.T(T))
        dut (.clk(clk), .rst_n(rst_n), .start(start), .valid_in(valid_in),
             .score(score), .valid_out(valid_out), .prob(prob));

    always #5 clk = ~clk;

    integer c, t, errors = 0;

    initial begin
        $readmemh("golden/softmax.hex", vec);
        #20 rst_n = 1'b1; #10;

        for (c = 0; c < N_CASES; c = c + 1) begin
            // 1) start
            @(negedge clk); start <= 1'b1;
            @(negedge clk); start <= 1'b0;
            // 2) 喂 T 个 score
            for (t = 0; t < T; t = t + 1) begin
                @(negedge clk); valid_in <= 1'b1; score <= vec[c*2*T + t];
            end
            @(negedge clk); valid_in <= 1'b0;
            // 3) 收 T 个 prob，比对（用边沿触发，避免同一脉冲读两次）
            for (t = 0; t < T; t = t + 1) begin
                @(posedge valid_out);
                @(negedge clk);
                if (prob !== vec[c*2*T + T + t]) begin
                    errors = errors + 1;
                    $display("FAIL case%0d[%0d]: p=%0d expect=%0d",
                             c, t, prob, vec[c*2*T + T + t]);
                end
            end
        end

        #20;
        if (errors == 0) $display("softmax: ALL %0d cases PASSED", N_CASES);
        else $display("softmax: %0d ERRORS", errors);
        $finish;
    end
endmodule

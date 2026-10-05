`timescale 1ns/1ps
// dot_product_tb.v —— 点积自校验
// a=[1,2,3,4], b=[5,6,7,8] -> dot = 70
module dot_product_tb;
    parameter LEN = 4, DATA_W = 16;
    reg clk = 0, rst_n = 0, valid_in = 0;
    reg signed [15:0] a = 0, b = 0;
    wire valid_out;
    wire signed [31:0] result;

    dot_product #(.LEN(LEN), .DATA_W(DATA_W))
        dut (.clk(clk), .rst_n(rst_n), .valid_in(valid_in), .a(a), .b(b),
             .valid_out(valid_out), .result(result));

    always #5 clk = ~clk;

    integer i, errors = 0;
    reg signed [15:0] av [0:3];
    reg signed [15:0] bv [0:3];

    initial begin
        av[0]=1; av[1]=2; av[2]=3; av[3]=4;
        bv[0]=5; bv[1]=6; bv[2]=7; bv[3]=8;
        #20 rst_n = 1'b1; #10;
        for (i = 0; i < LEN; i = i + 1) begin
            @(negedge clk);
            valid_in <= 1'b1; a <= av[i]; b <= bv[i];
        end
        @(negedge clk); valid_in <= 1'b0;
        @(negedge clk);
        if (result !== 70) begin
            errors = errors + 1;
            $display("FAIL: dot = %0d (expect 70)", result);
        end else $display("PASS: dot = %0d", result);

        #20;
        if (errors == 0) $display("ALL PASSED"); else $display("%0d ERRORS", errors);
        $finish;
    end
endmodule

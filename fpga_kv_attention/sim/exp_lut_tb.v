`timescale 1ns/1ps
// exp_lut_tb.v —— exp 查找表自校验（与 golden/exp_lut.hex 对拍）
module exp_lut_tb;
    reg [7:0] addr = 0;
    wire [15:0] val;

    exp_lut dut (.addr(addr), .val(val));

    reg [15:0] mem [0:255];
    integer i, errors = 0;

    initial begin
        $readmemh("golden/exp_lut.hex", mem);
        for (i = 0; i < 256; i = i + 1) begin
            addr = i;
            #1;   // 组合逻辑稳定
            if (val !== mem[i]) begin
                errors = errors + 1;
                if (errors <= 5)
                    $display("FAIL: addr=%0d val=%0d expect=%0d", i, val, mem[i]);
            end
        end
        if (errors == 0) $display("exp_lut: ALL 256 PASSED");
        else $display("exp_lut: %0d ERRORS / 256", errors);
        $finish;
    end
endmodule

`timescale 1ns/1ps
// q88_to_fp16_tb.v —— Q8.8 -> FP16 转换器自校验
// 读 golden/q88_fp16.hex：首字 = case 数，之后每个 case 两字（q88, fp16）。
module q88_to_fp16_tb;
    reg [15:0] vec [0:1023];
    reg signed [15:0] q88 = 0;
    wire [15:0] fp16;
    q88_to_fp16 dut (.q88(q88), .fp16(fp16));

    integer i, n, errors = 0;
    reg [15:0] expect;

    initial begin
        $readmemh("golden/q88_fp16.hex", vec);
        n = vec[0];
        for (i = 0; i < n; i = i + 1) begin
            q88    = $signed(vec[1 + 2*i]);
            expect = vec[2 + 2*i];
            #1;
            if (fp16 !== expect) begin
                errors = errors + 1;
                if (errors <= 20)
                    $display("FAIL q88=%d -> fp16=%04x (expect %04x)", q88, fp16, expect);
            end
        end
        if (errors == 0) $display("q88_to_fp16: ALL %0d cases PASSED", n);
        else $display("q88_to_fp16: %0d ERRORS", errors);
        $finish;
    end
endmodule

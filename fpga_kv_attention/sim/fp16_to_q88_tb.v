`timescale 1ns/1ps
// fp16_to_q88_tb.v —— FP16 -> Q8.8 转换器自校验
// 读 golden/fp16_q88.hex：首字 = case 数，之后每个 case 两字（fp16, q88）。
module fp16_to_q88_tb;
    reg [15:0] vec [0:1023];
    reg [15:0] fp16 = 0;
    wire signed [15:0] q88;
    fp16_to_q88 dut (.fp16(fp16), .q88(q88));

    integer i, n, errors = 0;
    reg signed [15:0] expect;

    initial begin
        $readmemh("golden/fp16_q88.hex", vec);
        n = vec[0];
        for (i = 0; i < n; i = i + 1) begin
            fp16   = vec[1 + 2*i];
            expect = $signed(vec[2 + 2*i]);
            #1;
            if (q88 !== expect) begin
                errors = errors + 1;
                if (errors <= 20)
                    $display("FAIL fp16=%04x -> q88=%d (expect %d)",
                             fp16, q88, expect);
            end
        end
        if (errors == 0) $display("fp16_to_q88: ALL %0d cases PASSED", n);
        else $display("fp16_to_q88: %0d ERRORS", errors);
        $finish;
    end
endmodule

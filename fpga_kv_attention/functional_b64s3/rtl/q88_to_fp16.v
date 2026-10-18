`timescale 1ns/1ps
// ============================================================================
// q88_to_fp16.v —— Q8.8 有符号 -> IEEE 754 half-precision（fp16_to_q88 的逆）
//
// 组合逻辑，1 拍。round-half-away；-32768(-128.0) 正常表示。
// 用途：attention 输出 out[31:0](Q8.24) 先算术右移 16 得 Q8.8，再转 FP16 回传
// （NUM-001 未冻结，此为占位；最终 scale/舍入待定）。
// ============================================================================
module q88_to_fp16 (
    input  wire signed [15:0] q88,   // Q8.8，值 = int/256
    output reg  [15:0] fp16          // IEEE 754 half
);
    wire        sign = q88[15];
    wire [15:0] mag  = sign ? (~q88[15:0] + 16'd1) : q88[15:0];  // 0..32768

    // 最高置位位置 L（0..15）
    reg [3:0] L;
    always @(*) begin
        if      (mag[15]) L = 4'd15;
        else if (mag[14]) L = 4'd14;
        else if (mag[13]) L = 4'd13;
        else if (mag[12]) L = 4'd12;
        else if (mag[11]) L = 4'd11;
        else if (mag[10]) L = 4'd10;
        else if (mag[9])  L = 4'd9;
        else if (mag[8])  L = 4'd8;
        else if (mag[7])  L = 4'd7;
        else if (mag[6])  L = 4'd6;
        else if (mag[5])  L = 4'd5;
        else if (mag[4])  L = 4'd4;
        else if (mag[3])  L = 4'd3;
        else if (mag[2])  L = 4'd2;
        else if (mag[1])  L = 4'd1;
        else              L = 4'd0;
    end

    // 规格化到 [1024, 2048)：e = L+7，significand = 1024+m
    reg [15:0] sig;    // [1024, 2048)，舍入进位时暂存 2048
    reg [4:0]  exp;
    reg        zero;
    always @(*) begin
        zero = (mag == 16'd0);
        if (mag == 16'd0) begin
            sig = 16'd0; exp = 5'd0;
        end else if (L >= 4'd10) begin
            if (L == 4'd10)
                sig = mag;                                   // 无舍入
            else
                sig = (mag + (16'd1 << (L - 4'd11))) >> (L - 4'd10);  // 四舍五入
            exp = 5'd7 + L;
            if (sig == 16'd2048) begin                       // 舍入进位
                sig = 16'd1024;
                exp = exp + 1'b1;
            end
        end else begin
            sig = mag << (4'd10 - L);                        // 左移精确
            exp = 5'd7 + L;
        end
    end

    always @(*) begin
        if (zero) fp16 = {sign, 15'd0};
        else       fp16 = {sign, exp[4:0], sig[9:0]};
    end
endmodule

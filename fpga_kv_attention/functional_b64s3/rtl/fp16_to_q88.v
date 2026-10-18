`timescale 1ns/1ps
// ============================================================================
// fp16_to_q88.v —— IEEE 754 half-precision -> Q8.8 有符号定点（NUM-009）
//
// 组合逻辑，1 拍出结果。用于把 NPU 经 PCIe 送来的 FP16 Q/K/V 转成
// Attention datapath 的共享定点格式 Q8.8。
//
// 特殊值处理：
//   e=0  (zero/subnormal) -> 0   （subnormal |v|<2^-14，Q8.8 下四舍五入为 0）
//   e=31 (inf/NaN)        -> 按符号饱和到 ±32767
//   正常值：mag = (1.m) * 2^(e-17)，round-half-away；超出 Q8.8 范围饱和到 ±32767。
//   （Q8.8 负端 -128.0=-32768 未单独表示，-127.996=-32767 为负饱和值）
// ============================================================================
module fp16_to_q88 (
    input  wire [15:0] fp16,           // IEEE 754 half-precision（1s/5e/10m）
    output wire signed [15:0] q88      // Q8.8，clamp 到 [-32767, 32767]
);
    wire        s   = fp16[15];
    wire [4:0]  e   = fp16[14:10];
    wire [9:0]  m   = fp16[9:0];
    wire [10:0] sig = {1'b1, m};       // 1.m = 1024 + m

    reg [26:0] mag;
    always @(*) begin
        if (e == 5'd0) begin
            mag = 27'd0;                                        // zero/subnormal -> 0
        end else if (e == 5'd31) begin
            mag = 27'd32767;                                    // inf/NaN -> 饱和
        end else if (e >= 5'd17) begin
            mag = {16'd0, sig} << (e - 5'd17);                  // 左移
            if (mag > 27'd32767) mag = 27'd32767;
        end else begin
            // 右移 + round-half-away：(sig + 2^(16-e)) >> (17-e)
            mag = ({16'd0, sig} + (27'd1 << (5'd16 - e))) >> (5'd17 - e);
        end
    end

    assign q88 = s ? -$signed(mag[15:0]) : $signed(mag[15:0]);
endmodule

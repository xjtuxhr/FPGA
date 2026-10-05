`timescale 1ns/1ps
// ============================================================================
// kv_dequant.v —— KVmix 反量化模块（定点，Verilog-2001）
//
//   x = q * scale + min
//
// 定点格式（v1 CANDIDATE，需与软件侧 NUM-001/002 对齐后冻结）：
//   q     无符号 Q_BITS 位，取值 0 .. 2^Q_BITS-1（2/3/4-bit）
//   scale 无符号 SCALE_W 位，Q0.8，真实值 = scale_int / 256
//   min   有符号 MIN_W 位，  Q8.8，真实值 = min_int  / 256
//   x     有符号 OUT_W 位，  Q8.8
//
// 关键性质：反量化结果 x 必然落在原激活的 [min, max] 范围内，因此
// x 不会超出 OUT_W 的表示范围，只需取低 OUT_W 位即可（无需饱和）。
// ============================================================================
module kv_dequant #(
    parameter Q_BITS  = 4,     // 量化位宽（2/3/4）
    parameter SCALE_W = 16,    // scale 位宽
    parameter MIN_W   = 16,    // min 位宽
    parameter OUT_W   = 16     // 输出位宽
)(
    input  wire clk,
    input  wire rst_n,
    input  wire valid_in,
    input  wire [Q_BITS-1:0]         q,
    input  wire [SCALE_W-1:0]        scale,
    input  wire signed [MIN_W-1:0]   min,
    output reg  valid_out,
    output reg  signed [OUT_W-1:0]   x
);

    // 1) 无符号乘：q * scale（Q_BITS 位 × SCALE_W 位）
    wire [Q_BITS+SCALE_W-1:0] prod = q * scale;

    // 2) 加有符号 min（符号扩展后相加，得到更宽的有符号和）
    wire signed [Q_BITS+SCALE_W:0] sum =
        $signed({1'b0, prod}) + $signed(min);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
            x         <= {OUT_W{1'b0}};
        end else begin
            valid_out <= valid_in;
            x         <= sum[OUT_W-1:0];   // 取低 OUT_W 位（结果必在范围内）
        end
    end

endmodule

`timescale 1ns/1ps
// ============================================================================
// kv_quant.v —— KVmix 量化模块（定点，Verilog-2001，v1 CANDIDATE）
//
//   q = clamp( round((x - min) * inv_scale), 0, QMAX )
//
// 定点格式（v1 CANDIDATE）：
//   x/min    有符号 Q8.8，真实值 = int / 256
//   inv_scale 无符号 Q8.8，真实值 = int / 256
//   inv_scale = 1 / scale = QMAX / (max - min)
//
// 设计说明：v1 让软件/上游预计算 inv_scale，硬件只做「减 + 乘 + 舍入 + 截位」，
// 避免真除法。真除法（由 min/max 现算 scale）留到后续版本，或由软件侧完成。
//
// 3-bit 特例（group=11，第 11 个元素只有 2-bit 精度）不在本模块内实现，
// 由 Q_BITS 参数与外部控制逻辑决定，这里只做统一的 clamp 到 [0, QMAX]。
// ============================================================================
module kv_quant #(
    parameter Q_BITS = 4,      // 量化位宽（2/3/4）
    parameter X_W    = 16,     // x/min 位宽（Q8.8 有符号）
    parameter INV_W  = 16      // inv_scale 位宽（Q8.8 无符号）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire valid_in,
    input  wire signed [X_W-1:0]   x,
    input  wire signed [X_W-1:0]   min,
    input  wire [INV_W-1:0]        inv_scale,
    output reg  valid_out,
    output reg  [Q_BITS-1:0]       q
);

    localparam QMAX = (1 << Q_BITS) - 1;   // 2^Q_BITS - 1

    // (x - min)：Q8.8，做差
    wire signed [X_W:0] diff = $signed(x) - $signed(min);

    // (x - min) * inv_scale：Q8.8 × Q8.8 = Q16.16
    wire signed [X_W+INV_W:0] prod = diff * $signed({1'b0, inv_scale});

    // 加 0.5（Q16.16 中的 2^15）后算术右移 16，实现四舍五入取整
    wire signed [X_W+INV_W:0] rnd   = prod + 33'sh8000;   // 33 位有符号常量 32768
    wire signed [X_W+INV_W-16:0] q_raw = rnd >>> 16;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            valid_out <= 1'b0;
            q         <= {Q_BITS{1'b0}};
        end else begin
            valid_out <= valid_in;
            if (q_raw > QMAX)
                q <= QMAX;                    // 上截位
            else if (q_raw < 0)
                q <= {Q_BITS{1'b0}};          // 下截位
            else
                q <= q_raw[Q_BITS-1:0];
        end
    end

endmodule

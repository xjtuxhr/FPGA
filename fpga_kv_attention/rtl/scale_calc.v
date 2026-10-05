`timescale 1ns/1ps
// ============================================================================
// scale_calc.v —— KVmix 量化 scale 计算（硬件版，替代软件预计算）
//
//   inv_scale = qmax / (max - min)
//   实现：span = max - min，inv_scale = (qmax << 16) / span（floor），
//         inv_scale 输出为 Q8.8（值 = int / 256）。
//
// 注意（NUM-002/KV-002 未冻结）：
//   - span 过小（max≈min）时 inv_scale 会超过 Q8.8 范围，本模块按 16 位截断；
//     实际使用需保证 span 足够大（量化组范围合理），或外部做饱和处理。
// ============================================================================
module scale_calc #(
    parameter Q_BITS = 4,
    parameter X_W    = 16
)(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire signed [X_W-1:0] max,
    input  wire signed [X_W-1:0] min,
    output wire done,
    output wire [15:0] inv_scale        // Q8.8
);
    localparam QMAX = (1 << Q_BITS) - 1;
    localparam [31:0] NUM = (QMAX << 16);   // 被除数 = qmax << 16（显式 32 位）

    // span = max - min（无符号差，max >= min 时为正）
    wire [15:0] span = $unsigned(max) - $unsigned(min);

    wire [15:0] div_rem;

    div_u32_u16 u_div (
        .clk(clk), .rst_n(rst_n), .start(start),
        .numerator(NUM), .denominator(span),
        .done(done), .quotient(inv_scale), .remainder(div_rem)
    );

endmodule

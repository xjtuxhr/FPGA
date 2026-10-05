`timescale 1ns/1ps
// ============================================================================
// attention_b_top.v —— Attention-only B 数据通路顶层（NUM-009 集成）
//
//   FP16 Q/K/V -> fp16_to_q88 -> gqa_attention -> output
//
// B 方案：KV 以 FP16 存储（此处为 FP16 输入），Attention 算术用共享定点 Q8.8。
// 输入/valid 直接透传给 gqa_attention，转换器为组合逻辑（1 拍）。
// 接口顺序与 gqa_attention 一致：Q(H×D)、K(G×T×D)、V(G×T×D) 各自流式输入。
// ============================================================================
module attention_b_top #(
    parameter H       = 9,     // 查询头数
    parameter G       = 3,     // KV 头数
    parameter D       = 64,    // head_dim
    parameter T       = 64,    // context 长度
    parameter DATA_W  = 16
)(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire q_valid,
    input  wire [15:0] q_fp16,          // FP16
    input  wire k_valid,
    input  wire [15:0] k_fp16,
    input  wire v_valid,
    input  wire [15:0] v_fp16,
    output wire out_valid,
    output wire signed [31:0] out,
    output wire [7:0] out_head,
    output wire [7:0] out_d
);
    wire signed [15:0] q_q88, k_q88, v_q88;

    fp16_to_q88 u_q (.fp16(q_fp16), .q88(q_q88));
    fp16_to_q88 u_k (.fp16(k_fp16), .q88(k_q88));
    fp16_to_q88 u_v (.fp16(v_fp16), .q88(v_q88));

    gqa_attention #(.H(H), .G(G), .D(D), .T(T), .DATA_W(DATA_W)) u_gqa (
        .clk(clk), .rst_n(rst_n), .start(start),
        .q_valid(q_valid), .q_in(q_q88),
        .k_valid(k_valid), .k_in(k_q88),
        .v_valid(v_valid), .v_in(v_q88),
        .out_valid(out_valid), .out(out), .out_head(out_head), .out_d(out_d));

endmodule

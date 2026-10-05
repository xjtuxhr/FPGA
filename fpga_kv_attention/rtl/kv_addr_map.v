`timescale 1ns/1ps
// ============================================================================
// kv_addr_map.v —— KV cache 在 FPGA DDR 中的地址映射（纯组合，DDR-002 输入）
//
// CANDIDATE 布局（16-bit 字寻址）：
//   data 区：K/V（FP16 或 Q8.8），每个 (g,t) 占 2*D 字（K: D 字，V: D 字）
//            data_addr = g*T*2*D + t*2*D + (is_K ? 0 : D)
//   meta 区：scale+min，每个 (g,t) 占 4 字（scale_K,min_K,scale_V,min_V）
//            meta_addr = G*T*2*D + (g*T+t)*4 + (is_K ? 0 : 2)
// 总量 = G*T*(2*D+4) 字。要求 T 为 2 的幂、g/t/is_K 在范围内。
// ============================================================================
module kv_addr_map #(
    parameter G = 3,     // KV 头数
    parameter D = 64,    // head_dim
    parameter T = 256    // context 长度
)(
    input  wire [7:0] g,        // 0..G-1
    input  wire [7:0] t,        // 0..T-1
    input  wire       is_K,     // 1=K 0=V
    output wire [31:0] data_addr,   // data 区字地址
    output wire [31:0] meta_addr    // meta 区字地址（scale 所在；min 在 +1）
);
    localparam TPD        = T * 2 * D;   // 每个 (g,t) 的 data 字数
    localparam DATA_DEPTH = G * TPD;     // data 区总字数

    assign data_addr = g*TPD + t*(2*D) + (is_K ? 0 : D);
    assign meta_addr = DATA_DEPTH + (g*T + t)*4 + (is_K ? 0 : 2);
endmodule

`timescale 1ns/1ps
// ============================================================================
// usr_loopback.v —— SGDMA H2C -> C2H 回环（链路自测用，非最终功能）
//
// 把 SGDMA 的 H2C AXI-ST 原样接回 C2H AXI-ST（经 axis_fifo 缓冲 + 背压）。
// 用于「写 1920B 进去、读回 1920B」的链路 + DMA 端到端自测，验证后再换成
// 真正的 attention endpoint。
// tuser 本版未用（置 0）；tdata/tkeep/tlast 透传。
// ============================================================================
module usr_loopback (
    input  wire clk,
    input  wire rst_n,
    // H2C：SGDMA 核心 -> 用户逻辑（卡内收数据）
    input  wire [127:0] m0_axis_h2c_tdata,
    input  wire [15:0]  m0_axis_h2c_tkeep,
    input  wire [15:0]  m0_axis_h2c_tuser,
    input  wire         m0_axis_h2c_tlast,
    input  wire         m0_axis_h2c_tvalid,
    output wire         m0_axis_h2c_tready,
    // C2H：用户逻辑 -> SGDMA 核心（卡内发数据）
    output wire [127:0] s0_axis_c2h_tdata,
    output wire [15:0]  s0_axis_c2h_tkeep,
    output wire [15:0]  s0_axis_c2h_tuser,
    output wire         s0_axis_c2h_tlast,
    output wire         s0_axis_c2h_tvalid,
    input  wire         s0_axis_c2h_tready
);
    axis_fifo #(.DEPTH(256), .DATA_W(128), .KEEP_W(16), .ADDR_W(8)) u_fifo (
        .clk(clk), .rst_n(rst_n),
        .s_valid(m0_axis_h2c_tvalid), .s_data(m0_axis_h2c_tdata),
        .s_keep(m0_axis_h2c_tkeep),   .s_last(m0_axis_h2c_tlast),
        .s_ready(m0_axis_h2c_tready),
        .m_valid(s0_axis_c2h_tvalid), .m_data(s0_axis_c2h_tdata),
        .m_keep(s0_axis_c2h_tkeep),   .m_last(s0_axis_c2h_tlast),
        .m_ready(s0_axis_c2h_tready));

    assign s0_axis_c2h_tuser = 16'd0;   // tuser 未用

endmodule

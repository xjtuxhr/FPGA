`timescale 1ns/1ps
// ============================================================================
// axis_16to128.v —— AXI-ST 16-bit -> 128-bit 宽度转换（C2H 方向）
//
// 收 8 拍 16-bit，拼成 1 拍 128-bit 输出（第 0 个字在低 16 位，第 7 个在高 16 位）。
// tlast 在包含末字的整拍输出；tkeep 输出全 1（本板帧无残缺尾拍）。
// ============================================================================
module axis_16to128 (
    input  wire clk,
    input  wire rst_n,
    // 16-bit 侧（producer）
    input  wire s_valid,
    input  wire [15:0] s_data,
    input  wire s_last,
    output wire s_ready,
    // 128-bit 侧（consumer）
    output reg  m_valid,
    output reg  [127:0] m_data,
    output reg  [15:0]  m_keep,
    output reg  m_last,
    input  wire m_ready
);
    reg [127:0] buf_r;
    reg [2:0]   idx;        // 0..7（已收字数）
    reg         full;       // 8 字已满，待输出
    reg         out_last;

    assign s_ready = !full;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            idx <= 3'd0; buf_r <= 128'd0; full <= 1'b0; out_last <= 1'b0;
            m_valid <= 1'b0; m_data <= 128'd0; m_keep <= 16'd0; m_last <= 1'b0;
        end else begin
            m_valid <= 1'b0;
            if (s_valid && s_ready) begin
                buf_r <= {s_data, buf_r[127:16]};     // 新字放高位，整体右移 16
                if (s_last) out_last <= 1'b1;
                if (idx == 3'd7) begin idx <= 3'd0; full <= 1'b1; end
                else idx <= idx + 1'b1;
            end
            if (full && m_ready) begin
                m_valid <= 1'b1;
                m_data  <= buf_r;
                m_keep  <= 16'hFFFF;
                m_last  <= out_last;
                full    <= 1'b0; out_last <= 1'b0;
            end
        end
    end

endmodule

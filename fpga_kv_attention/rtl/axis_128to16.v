`timescale 1ns/1ps
// ============================================================================
// axis_128to16.v —— AXI-ST 128-bit -> 16-bit 宽度转换（H2C 方向）
//
// 每 1 拍 128-bit 拆成 8 拍 16-bit（element k = data[16k+15:16k]，低 16 位在前）。
// tlast 在最后一拍（idx==7）透传；tkeep 本版忽略（本板帧无残缺尾拍，全 1）。
// 有 1 拍吞吐间隙（接受 1 拍后下一拍才开始出），attention 是瓶颈，无影响。
// ============================================================================
module axis_128to16 (
    input  wire clk,
    input  wire rst_n,
    // 128-bit 侧（producer）
    input  wire s_valid,
    input  wire [127:0] s_data,
    input  wire [15:0]  s_keep,   // 本版忽略（帧全 1）
    input  wire s_last,
    output wire s_ready,
    // 16-bit 侧（consumer）
    output reg  m_valid,
    output reg  [15:0] m_data,
    output reg  m_last,
    input  wire m_ready
);
    reg [127:0] buf_r;
    reg         buf_last;
    reg [2:0]   idx;      // 0..7
    reg         busy;

    assign s_ready = !busy;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy <= 1'b0; idx <= 3'd0; buf_r <= 128'd0; buf_last <= 1'b0;
            m_valid <= 1'b0; m_data <= 16'd0; m_last <= 1'b0;
        end else begin
            m_valid <= 1'b0;
            if (!busy) begin
                if (s_valid) begin
                    buf_r <= s_data; buf_last <= s_last; idx <= 3'd0; busy <= 1'b1;
                end
            end else begin
                if (m_ready) begin
                    m_valid <= 1'b1;
                    m_data  <= buf_r >> (16*idx);          // element idx
                    m_last  <= buf_last && (idx == 3'd7);
                    if (idx == 3'd7) begin busy <= 1'b0; idx <= 3'd0; end
                    else idx <= idx + 1'b1;
                end
            end
        end
    end

endmodule

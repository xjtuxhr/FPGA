`timescale 1ns/1ps
// ============================================================================
// axis_fifo.v —— AXI-ST 风格同步 FIFO（valid/last/ready + tkeep 握手）
//
// 泛化：SGDMA 128-bit 接口（DATA_W=128, KEEP_W=16）或 16-bit 数据流
// （DATA_W=16, KEEP_W=2）。收/发 FIFO 用同一模块（DEPTH 参数化）。
// 首字回退（fall-through）：写后 1 拍 m_valid 拉高；满时 s_ready 拉低背压。
// ============================================================================
module axis_fifo #(
    parameter DEPTH  = 256,    // 深度（2 的幂）
    parameter DATA_W = 128,
    parameter KEEP_W = 16,     // 每字字节数（= DATA_W/8）
    parameter ADDR_W = 8       // log2(DEPTH)
)(
    input  wire clk,
    input  wire rst_n,
    // 写侧（producer）
    input  wire s_valid,
    input  wire [DATA_W-1:0] s_data,
    input  wire [KEEP_W-1:0] s_keep,
    input  wire s_last,          // 包末拍（TLAST）
    output wire s_ready,
    // 读侧（consumer）
    output wire m_valid,
    output wire [DATA_W-1:0] m_data,
    output wire [KEEP_W-1:0] m_keep,
    output wire m_last,
    input  wire m_ready
);
    reg [DATA_W-1:0] mem [0:DEPTH-1];
    reg [KEEP_W-1:0] keep_mem [0:DEPTH-1];
    reg [0:DEPTH-1]  last_mem;
    reg [ADDR_W-1:0] wptr, rptr;
    reg [ADDR_W:0]   count;    // 0..DEPTH

    wire do_write = s_valid && s_ready;
    wire do_read  = m_valid && m_ready;

    assign s_ready = (count < DEPTH);
    assign m_valid = (count != 0);
    assign m_data  = mem[rptr];
    assign m_keep  = keep_mem[rptr];
    assign m_last  = last_mem[rptr];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wptr  <= {ADDR_W{1'b0}};
            rptr  <= {ADDR_W{1'b0}};
            count <= {(ADDR_W+1){1'b0}};
        end else begin
            if (do_write) begin
                mem[wptr]      <= s_data;
                keep_mem[wptr] <= s_keep;
                last_mem[wptr] <= s_last;
                wptr <= wptr + 1'b1;
            end
            if (do_read) rptr <= rptr + 1'b1;
            if (do_write && !do_read)      count <= count + 1'b1;
            else if (!do_write && do_read) count <= count - 1'b1;
        end
    end

endmodule

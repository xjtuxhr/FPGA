`timescale 1ns/1ps
// ============================================================================
// axi4_master.v —— 极简 AXI4 Master（突发读写，自动多 burst 拆分）
//
// 面向 DDR IP（ui_ddr）的 AXI4 Slave：128-bit 数据、4-bit ID、28-bit 字节地址。
// 单 outstanding；ID 固定 0、size=16B、burst=INCR。
// 控制通道（AW/AR/B）寄存器；数据通道（W/R）组合逻辑直通。
// 超过 4096B（256 拍）的传输自动拆成多个 AXI burst。
// ============================================================================
module axi4_master #(
    parameter ADDR_W = 28,
    parameter ID_W   = 4,
    parameter DATA_W = 128,
    parameter TIMEOUT_CYCLES = 133333333
)(
    input  wire clk,
    input  wire rst_n,
    // 写命令 + 数据流（128-bit/拍）
    input  wire wr_req,
    input  wire [ADDR_W-1:0] wr_addr,
    input  wire [23:0] wr_bytes,       // 16B 整数倍
    input  wire wr_valid,
    input  wire [DATA_W-1:0] wr_data,
    output wire wr_ready,
    output reg  wr_done,               // 脉冲
    // 读命令 + 数据流
    input  wire rd_req,
    input  wire [ADDR_W-1:0] rd_addr,
    input  wire [23:0] rd_bytes,
    output wire rd_valid,
    output wire [DATA_W-1:0] rd_data,
    input  wire rd_ready,
    output reg  rd_done,               // 脉冲
    output reg  cmd_error,             // terminal error; reset before reuse
    // AXI AW
    output reg  [ID_W-1:0]   m_axi_awid,
    output reg  [ADDR_W-1:0] m_axi_awaddr,
    output reg  [7:0]  m_axi_awlen,
    output reg  [2:0]  m_axi_awsize,
    output reg  [1:0]  m_axi_awburst,
    output reg  m_axi_awvalid,
    input  wire m_axi_awready,
    // AXI W（组合直通）
    output wire [DATA_W-1:0] m_axi_wdata,
    output wire [DATA_W/8-1:0] m_axi_wstrb,
    output wire m_axi_wlast,
    output wire m_axi_wvalid,
    input  wire m_axi_wready,
    // AXI B
    input  wire [ID_W-1:0] m_axi_bid,
    input  wire [1:0]  m_axi_bresp,
    input  wire m_axi_bvalid,
    output reg  m_axi_bready,
    // AXI AR
    output reg  [ID_W-1:0]   m_axi_arid,
    output reg  [ADDR_W-1:0] m_axi_araddr,
    output reg  [7:0]  m_axi_arlen,
    output reg  [2:0]  m_axi_arsize,
    output reg  [1:0]  m_axi_arburst,
    output reg  m_axi_arvalid,
    input  wire m_axi_arready,
    // AXI R（组合直通）
    input  wire [ID_W-1:0] m_axi_rid,
    input  wire [DATA_W-1:0] m_axi_rdata,
    input  wire [1:0]  m_axi_rresp,
    input  wire m_axi_rlast,
    input  wire m_axi_rvalid,
    output wire m_axi_rready
);
    localparam [2:0] SIZE_16B = 3'd4;
    localparam [1:0] BURST_INCR = 2'd1;
    localparam [23:0] MAX_BURST_BYTES = 24'd4096;

    localparam S_IDLE=3'd0, S_WR_AW=3'd1, S_WR_W=3'd2, S_WR_B=3'd3,
               S_RD_AR=3'd4, S_RD_R=3'd5;
    reg [2:0] state;
    reg [23:0] bytes_left;
    reg [ADDR_W-1:0] cur_addr;
    reg [7:0] beat_cnt;
    reg [31:0] watchdog;
    reg read_error;

    // 当前 burst 的字节数/拍数：不超过 4096 且不跨 4KiB 边界
    wire [23:0] to_boundary = MAX_BURST_BYTES - {12'd0, cur_addr[11:0]};
    wire [23:0] cur_burst_bytes = (bytes_left > to_boundary) ? to_boundary : bytes_left;
    wire [7:0]  cur_burst_beats  = cur_burst_bytes[11:4];   // /16

    // ---- W 通道组合直通 ----
    wire in_wr = (state == S_WR_W);
    assign m_axi_wvalid = in_wr && wr_valid;
    assign m_axi_wdata  = wr_data;
    assign m_axi_wstrb  = {DATA_W/8{1'b1}};
    assign m_axi_wlast  = in_wr && (beat_cnt == cur_burst_beats - 8'd1);
    assign wr_ready     = in_wr && m_axi_wready;

    // ---- R 通道组合直通 ----
    wire in_rd = (state == S_RD_R);
    assign rd_valid    = in_rd && m_axi_rvalid;
    assign rd_data     = m_axi_rdata;
    assign m_axi_rready = in_rd && rd_ready;
    wire progress = (m_axi_awvalid && m_axi_awready) || (m_axi_wvalid && m_axi_wready) ||
                    (m_axi_bvalid && m_axi_bready) || (m_axi_arvalid && m_axi_arready) ||
                    (m_axi_rvalid && m_axi_rready);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE;
            bytes_left <= 24'd0; cur_addr <= 0; beat_cnt <= 8'd0;
            wr_done <= 1'b0; rd_done <= 1'b0;
            cmd_error <= 0; watchdog <= 0; read_error <= 0;
            m_axi_awvalid <= 1'b0; m_axi_bready <= 1'b0;
            m_axi_arvalid <= 1'b0;
            m_axi_awid <= 0; m_axi_awaddr <= 0; m_axi_awlen <= 0;
            m_axi_awsize <= SIZE_16B; m_axi_awburst <= BURST_INCR;
            m_axi_arid <= 0; m_axi_araddr <= 0; m_axi_arlen <= 0;
            m_axi_arsize <= SIZE_16B; m_axi_arburst <= BURST_INCR;
        end else begin
            wr_done <= 1'b0; rd_done <= 1'b0;
            if (state == S_IDLE || progress) watchdog <= 0;
            else watchdog <= watchdog+1'b1;
            case (state)
                S_IDLE: begin
                    if (wr_req) begin
                        cmd_error <= 0; read_error <= 0;
                        cur_addr <= wr_addr; bytes_left <= wr_bytes; state <= S_WR_AW;
                    end else if (rd_req) begin
                        cmd_error <= 0; read_error <= 0;
                        cur_addr <= rd_addr; bytes_left <= rd_bytes; state <= S_RD_AR;
                    end
                end

                S_WR_AW: begin
                    m_axi_awaddr  <= cur_addr;
                    m_axi_awlen   <= cur_burst_beats - 8'd1;
                    m_axi_awvalid <= 1'b1;
                    if (m_axi_awvalid && m_axi_awready) begin
                        m_axi_awvalid <= 1'b0;
                        beat_cnt <= 8'd0;
                        state <= S_WR_W;
                    end
                end

                S_WR_W: begin
                    if (wr_valid && wr_ready) begin
                        if (beat_cnt == cur_burst_beats - 8'd1) state <= S_WR_B;
                        else beat_cnt <= beat_cnt + 1'b1;
                    end
                end

                S_WR_B: begin
                    m_axi_bready <= 1'b1;
                    if (m_axi_bvalid && m_axi_bready) begin
                        if (m_axi_bresp != 0 || m_axi_bid != 0) cmd_error <= 1;
                        m_axi_bready <= 1'b0;
                        cur_addr   <= cur_addr + cur_burst_bytes;
                        bytes_left <= bytes_left - cur_burst_bytes;
                        if (bytes_left <= cur_burst_bytes) begin
                            wr_done <= 1'b1;
                            state <= S_IDLE;
                        end else begin
                            state <= S_WR_AW;
                        end
                    end
                end

                S_RD_AR: begin
                    m_axi_araddr  <= cur_addr;
                    m_axi_arlen   <= cur_burst_beats - 8'd1;
                    m_axi_arvalid <= 1'b1;
                    if (m_axi_arvalid && m_axi_arready) begin
                        m_axi_arvalid <= 1'b0;
                        beat_cnt <= 8'd0;
                        state <= S_RD_R;
                    end
                end

                S_RD_R: begin
                    if (m_axi_rvalid && m_axi_rready) begin
                        if (m_axi_rresp != 0 || m_axi_rid != 0) read_error <= 1;
                        if (m_axi_rlast != (beat_cnt == cur_burst_beats-8'd1)) begin
                            cmd_error <= 1; rd_done <= 1; state <= S_IDLE;
                        end else if (m_axi_rlast) begin
                            beat_cnt <= 0;
                            cur_addr   <= cur_addr + cur_burst_bytes;
                            bytes_left <= bytes_left - cur_burst_bytes;
                            if (bytes_left <= cur_burst_bytes) begin
                                rd_done <= 1'b1;
                                if (read_error || m_axi_rresp != 0 || m_axi_rid != 0) cmd_error <= 1;
                                state <= S_IDLE;
                            end else begin
                                state <= S_RD_AR;
                            end
                        end else beat_cnt <= beat_cnt+1'b1;
                    end
                end
            endcase
            // A timeout is fail-stop, not an AXI cancellation. The operator
            // must reinitialize DDR if an accepted transaction is outstanding.
            if (state != S_IDLE && !progress && watchdog == TIMEOUT_CYCLES-1) begin
                cmd_error <= 1; state <= S_IDLE;
                wr_done <= (state <= S_WR_B);
                rd_done <= (state >= S_RD_AR);
                m_axi_awvalid <= 0; m_axi_arvalid <= 0; m_axi_bready <= 0;
            end
        end
    end

endmodule

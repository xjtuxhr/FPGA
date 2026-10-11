`timescale 1ns/1ps
// ============================================================================
// v2_endpoint.v —— PCIe v2 协议 endpoint（SGDMA AXI-ST 用户逻辑）
//
// 认 32B 头，按 op 干活：TEST=2 回显前 1152B；RESET_CACHE=1 回 32B ack；
// ATTENTION=0 暂未实现（回 32B ack 占位）。CRC-32/ISO-HDLC 覆盖清空 crc 的
// header + payload。帧 H2C 1952B / C2H 1184B，全 16B 整拍。单请求在途。
// ============================================================================
module v2_endpoint (
    input  wire clk,
    input  wire rst_n,
    input  wire [127:0] m0_axis_h2c_tdata,
    input  wire [15:0]  m0_axis_h2c_tkeep,
    input  wire [15:0]  m0_axis_h2c_tuser,
    input  wire         m0_axis_h2c_tlast,
    input  wire         m0_axis_h2c_tvalid,
    output wire         m0_axis_h2c_tready,
    output reg  [127:0] s0_axis_c2h_tdata,
    output reg  [15:0]  s0_axis_c2h_tkeep,
    output reg  [15:0]  s0_axis_c2h_tuser,
    output reg          s0_axis_c2h_tlast,
    output reg          s0_axis_c2h_tvalid,
    input  wire         s0_axis_c2h_tready
);
    localparam [31:0] MAGIC = 32'h584D564B;
    localparam [2:0]  OP_ATTN = 3'd0, OP_RESET = 3'd1, OP_TEST = 3'd2;
    localparam [15:0] RESP_PAYLEN_TEST = 16'd1152;

    reg [2:0]  op_r;
    reg [7:0]  layer_r;
    reg [31:0] position_r, seq_r;
    reg [31:0] req_crc_field;

    // 请求 CRC / 响应 CRC
    reg        req_crc_init, req_crc_valid;
    reg [127:0] req_crc_data;
    wire [31:0] req_crc;
    crc32_ref u_req_crc (.clk(clk), .rst_n(rst_n), .init(req_crc_init),
                         .valid(req_crc_valid), .data(req_crc_data), .crc(req_crc));
    reg        resp_crc_init, resp_crc_valid;
    reg [127:0] resp_crc_data;
    wire [31:0] resp_crc;
    crc32_ref u_resp_crc (.clk(clk), .rst_n(rst_n), .init(resp_crc_init),
                          .valid(resp_crc_valid), .data(resp_crc_data), .crc(resp_crc));

    // 回显 FIFO（1152B = 72 拍）
    reg        fifo_wr, fifo_wr_last;
    reg [127:0] fifo_wr_data;
    wire       fifo_wr_ready;
    wire       fifo_rd_valid, fifo_rd_last;
    wire [127:0] fifo_rd_data;
    wire       fifo_rd_en;
    axis_fifo #(.DEPTH(128), .DATA_W(128), .KEEP_W(16), .ADDR_W(7)) u_fifo (
        .clk(clk), .rst_n(rst_n),
        .s_valid(fifo_wr), .s_data(fifo_wr_data), .s_keep(16'hFFFF),
        .s_last(fifo_wr_last), .s_ready(fifo_wr_ready),
        .m_valid(fifo_rd_valid), .m_data(fifo_rd_data), .m_keep(),
        .m_last(fifo_rd_last), .m_ready(fifo_rd_en));

    // 响应头（TX 用，已锁存字段）
    wire [15:0]  resp_payload_len = (op_r == OP_RESET) ? 16'd0 : RESP_PAYLEN_TEST;
    wire [127:0] resp_hdr0 = {position_r, 24'd0, layer_r, 8'd0, {5'd0, op_r}, 16'd2, MAGIC};
    wire [127:0] resp_hdr1 = {32'd0, resp_crc, 16'd0, resp_payload_len, seq_r};

    localparam S_H0=3'd0, S_H1=3'd1, S_PAY=3'd2, S_TX0=3'd3, S_TX1=3'd4, S_TXP=3'd5;
    reg [2:0] state;
    reg [7:0] pay_cnt;

    assign m0_axis_h2c_tready = (state == S_H0 || state == S_H1 || state == S_PAY);
    // 回显 FIFO 读使能（组合，避免非阻塞导致的重复读）
    assign fifo_rd_en = (state == S_TXP) && s0_axis_c2h_tready;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_H0; pay_cnt <= 8'd0;
            op_r <= 0; layer_r <= 0; position_r <= 0; seq_r <= 0; req_crc_field <= 0;
            req_crc_init <= 0; req_crc_valid <= 0; req_crc_data <= 0;
            resp_crc_init <= 0; resp_crc_valid <= 0; resp_crc_data <= 0;
            fifo_wr <= 0; fifo_wr_data <= 0; fifo_wr_last <= 0;
            s0_axis_c2h_tdata <= 0; s0_axis_c2h_tkeep <= 0; s0_axis_c2h_tuser <= 0;
            s0_axis_c2h_tlast <= 0; s0_axis_c2h_tvalid <= 0;
        end else begin
            req_crc_init <= 0; req_crc_valid <= 0;
            resp_crc_init <= 0; resp_crc_valid <= 0;
            fifo_wr <= 0;
            s0_axis_c2h_tvalid <= 0;

            case (state)
                // 头拍 0（也是 idle）
                S_H0: begin
                    if (m0_axis_h2c_tvalid) begin
                        op_r       <= m0_axis_h2c_tdata[55:48];
                        layer_r    <= m0_axis_h2c_tdata[71:64];
                        position_r <= m0_axis_h2c_tdata[127:96];
                        req_crc_valid <= 1'b1;
                        req_crc_data  <= m0_axis_h2c_tdata;
                        resp_crc_valid <= 1'b1;
                        resp_crc_data  <= {m0_axis_h2c_tdata[127:96], 24'd0,
                                           m0_axis_h2c_tdata[71:64], 8'd0,
                                           m0_axis_h2c_tdata[55:48], 16'd2, MAGIC};
                        state <= S_H1;
                    end else begin
                        req_crc_init  <= 1'b1;   // idle 保持 CRC 复位
                        resp_crc_init <= 1'b1;
                    end
                end

                // 头拍 1
                S_H1: begin
                    if (m0_axis_h2c_tvalid) begin
                        seq_r         <= m0_axis_h2c_tdata[31:0];
                        req_crc_field <= m0_axis_h2c_tdata[95:64];
                        req_crc_valid <= 1'b1;
                        req_crc_data  <= {m0_axis_h2c_tdata[127:96], 32'd0,
                                          m0_axis_h2c_tdata[63:0]};
                        resp_crc_valid <= 1'b1;
                        resp_crc_data  <= {32'd0, 32'd0, 16'd0, resp_payload_len,
                                           m0_axis_h2c_tdata[31:0]};
                        pay_cnt <= 8'd0;
                        state <= (op_r == OP_RESET) ? S_TX0 : S_PAY;
                    end
                end

                // payload
                S_PAY: begin
                    if (m0_axis_h2c_tvalid) begin
                        req_crc_valid <= 1'b1;
                        req_crc_data  <= m0_axis_h2c_tdata;
                        if (op_r == OP_TEST && pay_cnt < 8'd72) begin
                            fifo_wr <= 1'b1;
                            fifo_wr_data <= m0_axis_h2c_tdata;
                            fifo_wr_last <= (pay_cnt == 8'd71);
                            resp_crc_valid <= 1'b1;
                            resp_crc_data  <= m0_axis_h2c_tdata;
                        end
                        if (pay_cnt == 8'd119) state <= S_TX0;
                        else pay_cnt <= pay_cnt + 1'b1;
                    end
                end

                // 发响应
                S_TX0: begin
                    if (s0_axis_c2h_tready) begin
                        s0_axis_c2h_tvalid <= 1'b1;
                        s0_axis_c2h_tdata  <= resp_hdr0;
                        s0_axis_c2h_tkeep  <= 16'hFFFF;
                        s0_axis_c2h_tuser  <= 16'd0;
                        s0_axis_c2h_tlast  <= 1'b0;
                        state <= S_TX1;
                    end
                end
                S_TX1: begin
                    if (s0_axis_c2h_tready) begin
                        s0_axis_c2h_tvalid <= 1'b1;
                        s0_axis_c2h_tdata  <= resp_hdr1;
                        s0_axis_c2h_tkeep  <= 16'hFFFF;
                        s0_axis_c2h_tuser  <= 16'd0;
                        s0_axis_c2h_tlast  <= (op_r == OP_RESET);
                        state <= (op_r == OP_RESET) ? S_H0 : S_TXP;
                    end
                end
                S_TXP: begin
                    if (fifo_rd_valid && s0_axis_c2h_tready) begin
                        s0_axis_c2h_tvalid <= 1'b1;
                        s0_axis_c2h_tdata  <= fifo_rd_data;
                        s0_axis_c2h_tkeep  <= 16'hFFFF;
                        s0_axis_c2h_tuser  <= 16'd0;
                        s0_axis_c2h_tlast  <= fifo_rd_last;
                        if (fifo_rd_last) state <= S_H0;
                    end
                end
            endcase
        end
    end

endmodule

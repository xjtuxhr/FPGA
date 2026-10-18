`timescale 1ns/1ps
// ============================================================================
// v2_endpoint.v —— PCIe v2 协议 endpoint（SGDMA AXI-ST 用户逻辑）
//
// 认 32B 头，按 op 干活：
//   ATTENTION=0：payload(120拍) 分流喂 attention_engine（Q 72 拍 / KV 48 拍），
//                引擎经 AXI4 写 KV 到 DDR、动态 GQA 算注意力，输出 576 个 FP16
//                打包成 1152B 响应回传。
//   RESET_CACHE=1：清 per-layer 历史计数 + 复位引擎，回 32B ack。
//   TEST=2：回显前 1152B。
// 请求校验（fault + error_code）：版本/keep/长度=1，CRC=2，非有限=3，seq 回退=4，
// 位置/容量=5，AXI 响应错误=6。CRC-32/ISO-HDLC 覆盖清空 crc 的 header + payload。
// 帧 H2C 1952B / C2H 1184B，全 16B 整拍。单请求在途。
// C2H 输出组合直通（valid 先于 ready），只寄存器状态机。
// ============================================================================
module v2_endpoint #(
    parameter MAX_T  = 256,
    parameter LAYERS = 30,
    parameter ADDR_W = 28,
    parameter ID_W   = 4,
    parameter DDR_GATE = 0,   // 1: 上板时使能 DDR init 门控（ddr_ready 未就绪则背压+压引擎）
    parameter SCORE_SHIFT = 0
)(
    input  wire clk,
    input  wire rst_n,
    input  wire ddr_ready,    // pll_locked && ddr_init_cal_done（DDR_GATE=1 时使用）
    input  wire [127:0] m0_axis_h2c_tdata,
    input  wire [15:0]  m0_axis_h2c_tkeep,
    input  wire [15:0]  m0_axis_h2c_tuser,
    input  wire         m0_axis_h2c_tlast,
    input  wire         m0_axis_h2c_tvalid,
    output wire         m0_axis_h2c_tready,
    output wire [127:0] s0_axis_c2h_tdata,
    output wire [15:0]  s0_axis_c2h_tkeep,
    output wire [15:0]  s0_axis_c2h_tuser,
    output wire         s0_axis_c2h_tlast,
    output wire         s0_axis_c2h_tvalid,
    input  wire         s0_axis_c2h_tready,
    output reg          fault,
    output reg  [3:0]   error_code,
    // AXI4 master（透出给 ui_ddr / 仿真 slave 模型）
    output wire [ID_W-1:0]   m_axi_awid, m_axi_arid,
    output wire [ADDR_W-1:0] m_axi_awaddr, m_axi_araddr,
    output wire [7:0]  m_axi_awlen, m_axi_arlen,
    output wire [2:0]  m_axi_awsize, m_axi_arsize,
    output wire [1:0]  m_axi_awburst, m_axi_arburst,
    output wire m_axi_awvalid, m_axi_arvalid,
    input  wire m_axi_awready, m_axi_arready,
    output wire [127:0] m_axi_wdata,
    output wire [15:0]  m_axi_wstrb,
    output wire m_axi_wlast, m_axi_wvalid,
    input  wire m_axi_wready,
    input  wire [ID_W-1:0] m_axi_bid, m_axi_rid,
    input  wire [1:0]  m_axi_bresp, m_axi_rresp,
    input  wire m_axi_bvalid, m_axi_rvalid,
    output wire m_axi_bready, m_axi_rready,
    input  wire [127:0] m_axi_rdata,
    input  wire m_axi_rlast
);
    localparam [31:0] MAGIC = 32'h584D564B;
    localparam [15:0] VERSION = 16'd2;
    localparam [15:0] RESP_PAYLEN = 16'd1152;
    localparam [15:0] PAY_BYTES   = 16'd1920;   // op 0/2 的 payload 字节数
    localparam [2:0]  OP_ATTN = 3'd0, OP_RESET = 3'd1, OP_TEST = 3'd2;
    localparam S_H0=4'd0, S_H1=4'd1, S_PAY=4'd2, S_CHK=4'd3,
               S_ENG=4'd4, S_TX0=4'd5, S_TX1=4'd6, S_TXP=4'd7,
               S_DROP=4'd8, S_FINISH=4'd9;

    reg [2:0]  op_r;
    reg [7:0]  layer_r;
    reg [31:0] position_r, seq_r;
    reg [31:0] req_crc_field;
    reg [31:0] last_seq;
    reg cache_initialized, recovery_needed;
    reg [15:0] hist_len [0:LAYERS-1];

    reg [3:0] state;
    reg [7:0] pay_cnt;
    reg [1:0] chk_cnt;
    reg [7:0] col_beat;
    reg [2:0] col_sub;
    reg [127:0] beat_buf;

    // 请求 CRC / 响应 CRC
    reg        req_crc_init, req_crc_valid;
    reg [127:0] req_crc_data;
    wire [31:0] req_crc;
    reg        resp_crc_init, resp_crc_valid;
    reg [127:0] resp_crc_data;
    wire [31:0] resp_crc;
    reg [31:0] resp_crc_latched;
    reg fifo_clear;

    // 响应 FIFO（TEST 回显 / ATTENTION 输出，各 1152B = 72 拍）
    reg        fifo_wr, fifo_wr_last;
    reg [127:0] fifo_wr_data;
    wire       fifo_wr_ready;
    wire       fifo_rd_valid, fifo_rd_last;
    wire [127:0] fifo_rd_data;
    wire       fifo_rd_en;

    // engine 接口
    reg  engine_clear, engine_start;
    wire engine_done, engine_error, engine_out_valid;
    wire [15:0] engine_out_fp16;
    wire payload_valid;
    wire [7:0]  payload_index;
    wire [127:0] payload_data;

    // DDR init 门控：DDR_GATE=0（仿真）默认始终 ready；=1（上板）由 ddr_ready 控制
    wire ddr_ok     = DDR_GATE ? ddr_ready : 1'b1;
    wire engine_rst = engine_clear || !ddr_ok;   // RESET op 或 DDR 未就绪时复位引擎

    crc32_ref u_req_crc (.clk(clk), .rst_n(rst_n), .init(req_crc_init),
                         .valid(req_crc_valid), .data(req_crc_data), .crc(req_crc));
    crc32_ref u_resp_crc (.clk(clk), .rst_n(rst_n), .init(resp_crc_init),
                          .valid(resp_crc_valid), .data(resp_crc_data), .crc(resp_crc));

    axis_fifo #(.DEPTH(128), .DATA_W(128), .KEEP_W(16), .ADDR_W(7)) u_fifo (
        .clk(clk), .rst_n(rst_n && !fifo_clear),
        .s_valid(fifo_wr), .s_data(fifo_wr_data), .s_keep(16'hFFFF),
        .s_last(fifo_wr_last), .s_ready(fifo_wr_ready),
        .m_valid(fifo_rd_valid), .m_data(fifo_rd_data), .m_keep(),
        .m_last(fifo_rd_last), .m_ready(fifo_rd_en));

    // 响应头（TX 用，已锁存字段）
    wire [15:0]  resp_payload_len = (op_r == OP_RESET) ? 16'd0 : RESP_PAYLEN;
    wire [127:0] resp_hdr0 = {position_r, 24'd0, layer_r, 8'd0, {5'd0, op_r}, VERSION, MAGIC};
    wire [127:0] resp_hdr1 = {32'd0, resp_crc_latched, 16'd0, resp_payload_len, seq_r};

    // payload 非有限 FP16 检测（exp==31）
    wire nonfinite_beat = (m0_axis_h2c_tdata[14:10]==5'd31)  | (m0_axis_h2c_tdata[30:26]==5'd31)  |
                          (m0_axis_h2c_tdata[46:42]==5'd31)  | (m0_axis_h2c_tdata[62:58]==5'd31)  |
                          (m0_axis_h2c_tdata[78:74]==5'd31)  | (m0_axis_h2c_tdata[94:90]==5'd31)  |
                          (m0_axis_h2c_tdata[110:106]==5'd31)| (m0_axis_h2c_tdata[126:122]==5'd31);

    wire h2c_fire = m0_axis_h2c_tvalid && m0_axis_h2c_tready;
    assign payload_valid = (state == S_PAY) && h2c_fire && (op_r == OP_ATTN);
    assign payload_index = pay_cnt;
    assign payload_data  = m0_axis_h2c_tdata;

    assign m0_axis_h2c_tready = (state == S_H0 || state == S_H1 || state == S_PAY || state == S_DROP) && ddr_ok;
    assign fifo_rd_en = (state == S_TXP) && s0_axis_c2h_tready;

    // ---- C2H 输出（组合直通，valid 先于 ready）----
    assign s0_axis_c2h_tvalid = (state == S_TX0) || (state == S_TX1) ||
                                ((state == S_TXP) && fifo_rd_valid);
    assign s0_axis_c2h_tdata  = (state == S_TX0) ? resp_hdr0 :
                                (state == S_TX1) ? resp_hdr1 : fifo_rd_data;
    assign s0_axis_c2h_tkeep  = 16'hFFFF;
    assign s0_axis_c2h_tuser  = 16'd0;
    assign s0_axis_c2h_tlast  = (state == S_TX0) ? 1'b0 :
                                (state == S_TX1) ? (op_r == OP_RESET) : fifo_rd_last;

    attention_engine #(.MAX_T(MAX_T), .LAYERS(LAYERS), .ADDR_W(ADDR_W), .ID_W(ID_W), .SCORE_SHIFT(SCORE_SHIFT)) u_engine (
        .clk(clk), .rst_n(rst_n),
        .clear_cache(engine_rst),
        .payload_valid(payload_valid), .payload_index(payload_index), .payload_data(payload_data),
        .start(engine_start), .layer(layer_r), .position(position_r),
        .busy(), .done(engine_done), .error(engine_error),
        .out_valid(engine_out_valid), .out_fp16(engine_out_fp16),
        .m_axi_awid(m_axi_awid), .m_axi_arid(m_axi_arid),
        .m_axi_awaddr(m_axi_awaddr), .m_axi_araddr(m_axi_araddr),
        .m_axi_awlen(m_axi_awlen), .m_axi_arlen(m_axi_arlen),
        .m_axi_awsize(m_axi_awsize), .m_axi_arsize(m_axi_arsize),
        .m_axi_awburst(m_axi_awburst), .m_axi_arburst(m_axi_arburst),
        .m_axi_awvalid(m_axi_awvalid), .m_axi_arvalid(m_axi_arvalid),
        .m_axi_wlast(m_axi_wlast), .m_axi_wvalid(m_axi_wvalid),
        .m_axi_bready(m_axi_bready), .m_axi_rready(m_axi_rready),
        .m_axi_awready(m_axi_awready), .m_axi_arready(m_axi_arready),
        .m_axi_wready(m_axi_wready), .m_axi_bvalid(m_axi_bvalid), .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb),
        .m_axi_bid(m_axi_bid), .m_axi_rid(m_axi_rid),
        .m_axi_bresp(m_axi_bresp), .m_axi_rresp(m_axi_rresp),
        .m_axi_rdata(m_axi_rdata));

    integer hl;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_H0; pay_cnt <= 8'd0; chk_cnt <= 2'd0;
            col_beat <= 8'd0; col_sub <= 3'd0; beat_buf <= 0;
            op_r <= 0; layer_r <= 0; position_r <= 0; seq_r <= 0;
            req_crc_field <= 0; last_seq <= 0;
            cache_initialized <= 0; recovery_needed <= 0;
            resp_crc_latched <= 0; fifo_clear <= 0;
            for (hl = 0; hl < LAYERS; hl = hl + 1) hist_len[hl] <= 16'd0;
            req_crc_init <= 0; req_crc_valid <= 0; req_crc_data <= 0;
            resp_crc_init <= 0; resp_crc_valid <= 0; resp_crc_data <= 0;
            fifo_wr <= 0; fifo_wr_data <= 0; fifo_wr_last <= 0;
            engine_clear <= 0; engine_start <= 0;
            fault <= 0; error_code <= 0;
        end else begin
            req_crc_init <= 0; req_crc_valid <= 0;
            resp_crc_init <= 0; resp_crc_valid <= 0;
            fifo_wr <= 0;
            fifo_clear <= 0;
            engine_start <= 0;

            case (state)
                // 头拍 0（也是 idle）
                S_H0: begin
                    if (h2c_fire) begin
                        fault <= 0; error_code <= 0;       // 新请求开始，清 fault
                        engine_clear <= 0;
                        op_r       <= m0_axis_h2c_tdata[55:48];
                        layer_r    <= m0_axis_h2c_tdata[71:64];
                        position_r <= m0_axis_h2c_tdata[127:96];
                        req_crc_valid <= 1'b1;
                        req_crc_init <= 1'b1;
                        req_crc_data  <= m0_axis_h2c_tdata;
                        resp_crc_valid <= 1'b1;
                        resp_crc_init <= 1'b1;
                        resp_crc_data  <= {m0_axis_h2c_tdata[127:96], 24'd0,
                                           m0_axis_h2c_tdata[71:64], 8'd0,
                                           m0_axis_h2c_tdata[55:48], VERSION, MAGIC};
                        if (m0_axis_h2c_tdata[31:0] != MAGIC ||
                            m0_axis_h2c_tdata[47:32] != VERSION ||
                            m0_axis_h2c_tdata[55:48] > 8'd2 ||    // 未知 op（只认 0/1/2）
                            m0_axis_h2c_tdata[63:56] != 8'd0 ||   // flags 必须 0
                            m0_axis_h2c_tdata[95:72] != 24'd0 ||  // padding0 必须 0
                            m0_axis_h2c_tkeep != 16'hFFFF) begin
                            fault <= 1'b1; error_code <= 4'd1;
                        end
                        if(m0_axis_h2c_tlast) begin
                            fault <= 1'b1; error_code <= 4'd1;
                            recovery_needed <= 1'b1; fifo_clear <= 1'b1;
                            state <= S_H0;
                        end else state <= S_H1;
                    end else begin
                        req_crc_init  <= 1'b1;   // idle 保持 CRC 复位
                        resp_crc_init <= 1'b1;
                    end
                end

                // 头拍 1
                S_H1: begin
                    if (h2c_fire) begin
                        seq_r         <= m0_axis_h2c_tdata[31:0];
                        req_crc_field <= m0_axis_h2c_tdata[95:64];
                        req_crc_valid <= 1'b1;
                        req_crc_data  <= {m0_axis_h2c_tdata[127:96], 32'd0,
                                          m0_axis_h2c_tdata[63:0]};
                        resp_crc_valid <= 1'b1;
                        resp_crc_data  <= {32'd0, 32'd0, 16'd0, resp_payload_len,
                                           m0_axis_h2c_tdata[31:0]};
                        // keep / seq / payload_len / position 校验
                        if (m0_axis_h2c_tkeep != 16'hFFFF) begin
                            fault <= 1'b1; error_code <= 4'd1;
                        end
                        if (m0_axis_h2c_tdata[63:48] != 16'd0 ||   // padding1 必须 0
                            m0_axis_h2c_tdata[127:96] != 32'd0) begin  // reserved 必须 0
                            if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd1; end
                        end
                        if (m0_axis_h2c_tdata[31:0] <= last_seq) begin
                            if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd4; end
                        end
                        if ((op_r == OP_RESET) ? (m0_axis_h2c_tdata[47:32] != 16'd0)
                                               : (m0_axis_h2c_tdata[47:32] != PAY_BYTES)) begin
                            if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd1; end
                        end
                        if (op_r == OP_ATTN) begin
                            if (!cache_initialized || recovery_needed || position_r >= MAX_T || layer_r >= LAYERS ||
                                position_r != hist_len[layer_r]) begin
                                if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd5; end
                            end
                        end
                        if (op_r == OP_RESET) begin
                            if(layer_r != 8'hff || position_r != 0 || !m0_axis_h2c_tlast) begin
                                if(error_code == 0) begin fault <= 1'b1; error_code <= 4'd1; end
                            end
                            chk_cnt <= 0;
                            state <= m0_axis_h2c_tlast ? S_CHK : S_DROP;
                        end else if (m0_axis_h2c_tlast) begin
                            // 非 RESET 帧只有 2 拍（0 payload）→ 长度错，不应答
                            if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd1; end
                            recovery_needed <= 1'b1; fifo_clear <= 1'b1;
                            state <= S_H0;
                        end else begin
                            pay_cnt <= 8'd0;
                            chk_cnt <= 2'd0;
                            state <= S_PAY;
                        end
                    end
                end

                // payload（op 0/2 各 120 拍；tlast 结束）
                S_PAY: begin
                    if (h2c_fire) begin
                        req_crc_valid <= 1'b1;
                        req_crc_data  <= m0_axis_h2c_tdata;
                        if (m0_axis_h2c_tkeep != 16'hFFFF) begin
                            if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd1; end
                        end
                        if (op_r == OP_ATTN && nonfinite_beat) begin
                            if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd3; end
                        end
                        if (op_r == OP_TEST && pay_cnt < 8'd72) begin
                            fifo_wr <= 1'b1;
                            fifo_wr_data <= m0_axis_h2c_tdata;
                            fifo_wr_last <= (pay_cnt == 8'd71);
                            resp_crc_valid <= 1'b1;
                            resp_crc_data  <= m0_axis_h2c_tdata;
                        end
                        if (m0_axis_h2c_tlast) begin
                            if (pay_cnt != 8'd119) begin
                                if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd1; end
                            end
                            state <= S_CHK;
                        end else begin
                            if(pay_cnt >= 8'd119 && error_code == 0) begin fault <= 1'b1; error_code <= 4'd1; end
                            if(pay_cnt != 8'hff) pay_cnt <= pay_cnt + 1'b1;
                        end
                    end
                end

                // 等请求 CRC 流水 + 比对，然后分发
                S_CHK: begin
                    chk_cnt <= chk_cnt + 1'b1;
                    if (chk_cnt == 2'd2) begin
                        if (req_crc != req_crc_field) begin
                            // CRC 错：fault=2，不应答，不启动引擎
                            if (error_code == 4'd0) begin fault <= 1'b1; error_code <= 4'd2; end
                            recovery_needed <= 1'b1; fifo_clear <= 1'b1;
                            state <= S_H0;
                        end else if (fault) begin
                            recovery_needed <= 1'b1; fifo_clear <= 1'b1;
                            state <= S_H0;   // 其它已检测的错误：不应答
                        end else if(op_r == OP_RESET) begin
                            last_seq <= seq_r;
                            for(hl=0; hl<LAYERS; hl=hl+1) hist_len[hl] <= 0;
                            cache_initialized <= 1'b1; recovery_needed <= 1'b0;
                            engine_clear <= 1'b1; fifo_clear <= 1'b1;
                            resp_crc_latched <= resp_crc;
                            state <= S_TX0;
                        end else if(recovery_needed) begin
                            fault <= 1'b1; error_code <= 4'd5;
                            fifo_clear <= 1'b1;
                            state <= S_H0;
                        end else if (op_r == OP_ATTN) begin
                            last_seq <= seq_r;
                            col_beat <= 8'd0; col_sub <= 3'd0; beat_buf <= 0;
                            engine_start <= 1'b1;
                            state <= S_ENG;
                        end else begin
                            last_seq <= seq_r;
                            resp_crc_latched <= resp_crc;
                            state <= S_TX0;  // TEST 回显
                        end
                    end
                end

                // 等引擎完成，同时收 576 个输出打包成 72 拍
                S_ENG: begin
                    if (engine_out_valid) begin
                        beat_buf <= {engine_out_fp16, beat_buf[127:16]};
                        if (col_sub == 3'd7) begin
                            fifo_wr <= 1'b1;
                            fifo_wr_data <= {engine_out_fp16, beat_buf[127:16]};
                            fifo_wr_last <= (col_beat == 8'd71);
                            resp_crc_valid <= 1'b1;
                            resp_crc_data  <= {engine_out_fp16, beat_buf[127:16]};
                            col_sub <= 3'd0;
                            col_beat <= col_beat + 8'd1;
                        end else begin
                            col_sub <= col_sub + 3'd1;
                        end
                    end
                    if (engine_done) begin
                        if (engine_error) begin
                            fault <= 1'b1; error_code <= 4'd6;
                            recovery_needed <= 1'b1; fifo_clear <= 1'b1;
                            state <= S_H0;
                        end else begin
                            hist_len[layer_r] <= position_r + 1'b1;
                            chk_cnt <= 0; state <= S_FINISH;
                        end
                    end
                end

                S_DROP: begin
                    if(h2c_fire && m0_axis_h2c_tlast) begin
                        recovery_needed <= 1'b1; fifo_clear <= 1'b1; state <= S_H0;
                    end
                end
                S_FINISH: begin
                    // Finish the registered CRC feed before exposing header 1.
                    chk_cnt <= chk_cnt + 1'b1;
                    if(chk_cnt == 2) begin resp_crc_latched <= resp_crc; state <= S_TX0; end
                end
                // 发响应（组合输出见上方 assign，此处只推进状态）
                S_TX0: begin
                    if (s0_axis_c2h_tready) state <= S_TX1;
                end
                S_TX1: begin
                    if (s0_axis_c2h_tready) state <= (op_r == OP_RESET) ? S_H0 : S_TXP;
                end
                S_TXP: begin
                    if (s0_axis_c2h_tready && fifo_rd_valid && fifo_rd_last) state <= S_H0;
                end
            endcase
        end
    end

endmodule

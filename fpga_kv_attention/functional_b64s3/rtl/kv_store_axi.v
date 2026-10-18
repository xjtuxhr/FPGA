`timescale 1ns/1ps
// ============================================================================
// kv_store_axi.v —— KV cache 存储（AXI4 后端，DDR 版）
//
// token t 的 K/V（G*2*D 个 16-bit 字）连续存放，字节地址 = t * G*2*D*2。
// D=64 → 每 token 48 拍（128-bit）。写数据可来自外部（PATTERN_WRITE=0，
// attention_engine 用）或内部模式（PATTERN_WRITE=1，旧自检用）。
// 支持层基址（USE_BASE_ADDR）与切片读（READ_SLICE：只读某 token 的一段字）。
// 检测 AXI 响应错误（BRESP/RRESP != OKAY）→ error 置位（sticky，复位清）。
// ============================================================================
module kv_store_axi #(
    parameter G = 3, D = 64, T = 256,
    parameter ADDR_W = 28, ID_W = 4,
    parameter PATTERN_WRITE = 1,  // 1: 内部生成写数据; 0: 外部 wr_data
    parameter USE_BASE_ADDR = 0, // 1: 地址 = base_addr + token*BYTES
    parameter READ_SLICE     = 0  // 1: 只读 rd_word_count 字（rd_word_offset 起）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire new_token,             // 写一个 token 的脉冲
    input  wire [15:0] token_id,
    input  wire rd_req,                // 读脉冲
    input  wire [15:0] rd_token,
    input  wire [15:0] rd_word_offset, // READ_SLICE：字偏移
    input  wire [15:0] rd_word_count,  // READ_SLICE：字数
    input  wire [ADDR_W-1:0] base_addr,// USE_BASE_ADDR：层基址
    input  wire [127:0] wr_data,       // PATTERN_WRITE=0：写数据拍
    input  wire wr_valid,              // PATTERN_WRITE=0：数据有效（常 1）
    output wire wr_ready,
    output wire [7:0] wr_beat_index,   // 当前要写的拍号（0..BEATS-1）
    output reg  error,                 // AXI 响应错误（sticky）
    output reg  rd_valid,
    output reg  [15:0] rd_data,
    output wire busy,
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
    localparam WORDS = G*2*D;
    localparam BEATS = WORDS / 8;
    localparam [23:0] BYTES = WORDS * 2;

    reg        axi_wr_req;
    wire       axi_wr_valid;
    reg [ADDR_W-1:0] axi_wr_addr;
    wire [127:0] axi_wr_data;
    wire       axi_wr_ready, axi_wr_done;
    reg        axi_rd_req;
    wire       axi_rd_ready;
    reg [ADDR_W-1:0] axi_rd_addr;
    wire [23:0] axi_rd_bytes;
    wire       axi_rd_valid;
    wire [127:0] axi_rd_data;
    wire       axi_rd_done;
    wire       axi_cmd_error;

    axi4_master #(.ADDR_W(ADDR_W), .ID_W(ID_W)) u_axi (
        .clk(clk), .rst_n(rst_n),
        .wr_req(axi_wr_req), .wr_addr(axi_wr_addr), .wr_bytes(BYTES),
        .wr_valid(axi_wr_valid), .wr_data(axi_wr_data),
        .wr_ready(axi_wr_ready), .wr_done(axi_wr_done),
        .rd_req(axi_rd_req), .rd_addr(axi_rd_addr), .rd_bytes(axi_rd_bytes),
        .rd_valid(axi_rd_valid), .rd_data(axi_rd_data),
        .rd_ready(axi_rd_ready), .rd_done(axi_rd_done), .cmd_error(axi_cmd_error),
        .m_axi_awid(m_axi_awid), .m_axi_awaddr(m_axi_awaddr), .m_axi_awlen(m_axi_awlen),
        .m_axi_awsize(m_axi_awsize), .m_axi_awburst(m_axi_awburst),
        .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast), .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid), .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(m_axi_bready),
        .m_axi_arid(m_axi_arid), .m_axi_araddr(m_axi_araddr), .m_axi_arlen(m_axi_arlen),
        .m_axi_arsize(m_axi_arsize), .m_axi_arburst(m_axi_arburst),
        .m_axi_arvalid(m_axi_arvalid), .m_axi_arready(m_axi_arready),
        .m_axi_rid(m_axi_rid), .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast), .m_axi_rvalid(m_axi_rvalid), .m_axi_rready(m_axi_rready));

    localparam S_IDLE=3'd0, S_WR_CMD=3'd1, S_WR_DATA=3'd2, S_WR_DONE=3'd3,
               S_RD_CMD=3'd4, S_RD_BEAT=3'd5, S_RD_UNPACK=3'd6;
    reg [2:0] state;
    reg [15:0] tkn_latch;
    reg [15:0] rd_off_latch, rd_cnt_latch;
    reg [ADDR_W-1:0] rd_base_latch;
    reg [7:0]  beat_cnt;
    reg [2:0]  sub_cnt;
    reg [127:0] beat_latch;

    // 读长度（切片读按 rd_word_count，否则整个 token）
    wire [15:0] rd_words = READ_SLICE ? rd_cnt_latch : WORDS;
    wire [7:0]  rd_beats = rd_words >> 3;
    assign axi_rd_bytes = {7'd0, rd_words[15:0], 1'b0};   // rd_words * 2（字节）

    // 内部模式写数据（PATTERN_WRITE=1，自检用）
    wire [15:0] wbase = tkn_latch*16'd384 + beat_cnt*16'd8;
    wire [127:0] wr_beat = {wbase+16'd7, wbase+16'd6, wbase+16'd5, wbase+16'd4,
                            wbase+16'd3, wbase+16'd2, wbase+16'd1, wbase+16'd0};

    // 写数据组合直通（和 beat_cnt 对齐）；外部数据经 wr_data，内部用模式
    assign axi_wr_valid = (state == S_WR_DATA) && (PATTERN_WRITE || wr_valid);
    assign axi_wr_data  = PATTERN_WRITE ? wr_beat : wr_data;
    assign wr_beat_index = beat_cnt;
    assign wr_ready     = (state == S_WR_DATA) && axi_wr_ready;

    assign busy = (state != S_IDLE);
    // 读背压：只在「等拍」状态拉高 ready，解包时拉低让 DDR 停住
    assign axi_rd_ready = (state == S_RD_BEAT);

    // ---- AXI 响应错误检测（sticky）----
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) error <= 1'b0;
        else begin
            if (m_axi_bvalid && m_axi_bready && (m_axi_bresp != 2'b00 || m_axi_bid != 0)) error <= 1'b1;
            if (m_axi_rvalid && m_axi_rready && (m_axi_rresp != 2'b00 || m_axi_rid != 0)) error <= 1'b1;
            if (axi_cmd_error) error <= 1'b1;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; tkn_latch <= 0; beat_cnt <= 0; sub_cnt <= 0; beat_latch <= 0;
            rd_off_latch <= 0; rd_cnt_latch <= 0; rd_base_latch <= 0;
            rd_valid <= 0; rd_data <= 0;
            axi_wr_req <= 0; axi_wr_addr <= 0;
            axi_rd_req <= 0; axi_rd_addr <= 0;
        end else begin
            rd_valid <= 0;
            axi_wr_req <= 0;
            axi_rd_req <= 0;
            case (state)
                S_IDLE: begin
                    if (new_token) begin
                        tkn_latch <= token_id; beat_cnt <= 0; state <= S_WR_CMD;
                    end else if (rd_req) begin
                        tkn_latch <= rd_token; beat_cnt <= 0;
                        rd_off_latch <= rd_word_offset;
                        rd_cnt_latch <= rd_word_count;
                        rd_base_latch <= base_addr;
                        state <= S_RD_CMD;
                    end
                end

                // ---- 写 ----
                S_WR_CMD: begin
                    axi_wr_req <= 1'b1;
                    axi_wr_addr <= (USE_BASE_ADDR ? base_addr : {ADDR_W{1'b0}}) + tkn_latch * BYTES;
                    state <= S_WR_DATA;
                end
                S_WR_DATA: begin
                    if (axi_wr_valid && axi_wr_ready) begin
                        if (beat_cnt == BEATS-1) state <= S_WR_DONE;
                        else beat_cnt <= beat_cnt + 1'b1;
                    end
                end
                S_WR_DONE: begin
                    if (axi_wr_done) state <= S_IDLE;
                end

                // ---- 读 ----
                S_RD_CMD: begin
                    axi_rd_req <= 1'b1;
                    axi_rd_addr <= (USE_BASE_ADDR ? rd_base_latch : {ADDR_W{1'b0}})
                                   + tkn_latch * BYTES
                                   + (READ_SLICE ? {rd_off_latch, 1'b0} : {ADDR_W{1'b0}});
                    beat_cnt <= 0;
                    state <= S_RD_BEAT;
                end
                S_RD_BEAT: begin
                    if (axi_rd_valid) begin
                        beat_latch <= axi_rd_data;   // 锁存 128-bit 拍
                        sub_cnt <= 0;
                        state <= S_RD_UNPACK;
                    end
                end
                S_RD_UNPACK: begin
                    rd_valid <= 1'b1;
                    rd_data <= beat_latch >> (16*sub_cnt);  // 逐字解包
                    if (sub_cnt == 3'd7) begin
                        if (beat_cnt == rd_beats-1) begin
                            state <= S_IDLE;
                        end else begin
                            beat_cnt <= beat_cnt + 1'b1;
                            state <= S_RD_BEAT;
                        end
                    end else sub_cnt <= sub_cnt + 1'b1;
                end
            endcase
            if (axi_cmd_error && state != S_IDLE) begin
                rd_valid <= 0; axi_wr_req <= 0; axi_rd_req <= 0; state <= S_IDLE;
            end
        end
    end

endmodule

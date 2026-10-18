`timescale 1ns/1ps
// Simulation-stage B path: FP16 cache, existing candidate Q8.8 arithmetic.
// Token layout: [K(G,D), V(G,D)], layer stride MAX_T*G*D*4 bytes.
// Read only the selected head's D-word slice, group -> token -> dimension.
// Stream all K then all V directly to GQA. No additional history buffer,
// no redundant full-token reads and no future tokens are read.
module attention_engine #(
    parameter MAX_T=256, LAYERS=30, ADDR_W=28, ID_W=4, SCORE_SHIFT=0
)(
    input wire clk, rst_n,
    input wire clear_cache,
    input wire payload_valid,
    input wire [7:0] payload_index,
    input wire [127:0] payload_data,
    input wire start,
    input wire [7:0] layer,
    input wire [31:0] position,
    output wire busy,
    output reg done, error,
    output wire out_valid,
    output wire [15:0] out_fp16,
    output wire [ID_W-1:0] m_axi_awid,
    output wire [ID_W-1:0] m_axi_arid,
    output wire [ADDR_W-1:0] m_axi_awaddr,
    output wire [ADDR_W-1:0] m_axi_araddr,
    output wire [7:0] m_axi_awlen,
    output wire [7:0] m_axi_arlen,
    output wire [2:0] m_axi_awsize,
    output wire [2:0] m_axi_arsize,
    output wire [1:0] m_axi_awburst,
    output wire [1:0] m_axi_arburst,
    output wire  m_axi_awvalid,
    output wire  m_axi_arvalid,
    output wire  m_axi_wlast,
    output wire  m_axi_wvalid,
    output wire  m_axi_bready,
    output wire  m_axi_rready,
    input wire  m_axi_awready,
    input wire  m_axi_arready,
    input wire  m_axi_wready,
    input wire  m_axi_bvalid,
    input wire  m_axi_rvalid,
    input wire  m_axi_rlast,
    output wire [127:0] m_axi_wdata,
    output wire [15:0] m_axi_wstrb,
    input wire [ID_W-1:0] m_axi_bid,
    input wire [ID_W-1:0] m_axi_rid,
    input wire [1:0] m_axi_bresp,
    input wire [1:0] m_axi_rresp,
    input wire [127:0] m_axi_rdata
);
    localparam H=9, G=3, D=64, TOKEN_BYTES=768;
    localparam IDLE=0, WRITE=1, WRITE_WAIT=2, ATT_START=3, Q_FEED=4,
               READ_CMD=5, READ_WORDS=6, ROUTE=7, COLLECT=8, Q_DRAIN=9;
    reg [3:0] state;
    reg [15:0] q_mem [0:H*D-1];
    reg [127:0] kv_payload [0:47];
    reg [15:0] pos_r, length_r, read_token;
    reg [ADDR_W-1:0] base_r;
    reg [9:0] count;
    reg [1:0] group_r;
    reg value_pass;
    integer lane;
    wire engine_rst_n = rst_n && !clear_cache;
    always @(posedge clk) begin
        if (payload_valid) begin
            if (payload_index < 72)
                for (lane=0; lane<8; lane=lane+1)
                    q_mem[payload_index*8+lane] <= payload_data[lane*16 +: 16];
            else if (payload_index < 120)
                kv_payload[payload_index-72] <= payload_data;
        end
    end

    wire kv_busy, kv_error, kv_valid;
    wire [15:0] kv_data;
    wire [7:0] write_index;
    kv_store_axi #(.G(G), .D(D), .T(MAX_T), .ADDR_W(ADDR_W),
        .ID_W(ID_W), .PATTERN_WRITE(0), .USE_BASE_ADDR(1), .READ_SLICE(1)) u_kv (
        .clk(clk), .rst_n(engine_rst_n), .new_token(state == WRITE),
        .token_id(pos_r), .rd_req(state == READ_CMD), .rd_token(read_token),
        .rd_word_offset((value_pass ? 16'd192 : 16'd0)+{8'd0,group_r,6'd0}),
        .rd_word_count(16'd64),
        .base_addr(base_r), .wr_data(kv_payload[write_index]), .wr_valid(1'b1),
        .wr_ready(), .wr_beat_index(write_index), .error(kv_error),
        .rd_valid(kv_valid), .rd_data(kv_data), .busy(kv_busy),
        .m_axi_awid(m_axi_awid),
        .m_axi_arid(m_axi_arid),
        .m_axi_awaddr(m_axi_awaddr),
        .m_axi_araddr(m_axi_araddr),
        .m_axi_awlen(m_axi_awlen),
        .m_axi_arlen(m_axi_arlen),
        .m_axi_awsize(m_axi_awsize),
        .m_axi_arsize(m_axi_arsize),
        .m_axi_awburst(m_axi_awburst),
        .m_axi_arburst(m_axi_arburst),
        .m_axi_awvalid(m_axi_awvalid),
        .m_axi_arvalid(m_axi_arvalid),
        .m_axi_wlast(m_axi_wlast),
        .m_axi_wvalid(m_axi_wvalid),
        .m_axi_bready(m_axi_bready),
        .m_axi_rready(m_axi_rready),
        .m_axi_awready(m_axi_awready),
        .m_axi_arready(m_axi_arready),
        .m_axi_wready(m_axi_wready),
        .m_axi_bvalid(m_axi_bvalid),
        .m_axi_rvalid(m_axi_rvalid),
        .m_axi_rlast(m_axi_rlast),
        .m_axi_wdata(m_axi_wdata),
        .m_axi_wstrb(m_axi_wstrb),
        .m_axi_bid(m_axi_bid),
        .m_axi_rid(m_axi_rid),
        .m_axi_bresp(m_axi_bresp),
        .m_axi_rresp(m_axi_rresp),
        .m_axi_rdata(m_axi_rdata));

    wire signed [15:0] q_fixed, kv_fixed;
    wire q_converted_valid,q_converted_last,kv_converted_valid,kv_converted_value;
    fp16_to_q88_pipe u_q (.clk(clk),.rst_n(engine_rst_n),
        .in_valid(state==Q_FEED),.in_tag(count==H*D-1),
        .fp16(q_mem[count]),.q88(q_fixed),.out_valid(q_converted_valid),.out_tag(q_converted_last));
    fp16_to_q88_pipe u_kv_convert (.clk(clk),.rst_n(engine_rst_n),
        .in_valid(state==READ_WORDS && kv_valid),.in_tag(value_pass),
        .fp16(kv_data),.q88(kv_fixed),.out_valid(kv_converted_valid),.out_tag(kv_converted_value));
    wire att_valid;
    wire signed [31:0] att_out;
    wire [7:0] att_head, att_d;
    gqa_attention #(.H(H), .G(G), .D(D), .T(MAX_T), .RUNTIME_T(1), .SCORE_SHIFT(SCORE_SHIFT)) u_att (
        .clk(clk), .rst_n(engine_rst_n), .start(state == ATT_START),
        .context_len(length_r),
        .q_valid(q_converted_valid), .q_in(q_fixed),
        .k_valid(kv_converted_valid && !kv_converted_value), .k_in(kv_fixed),
        .v_valid(kv_converted_valid && kv_converted_value), .v_in(kv_fixed),
        .out_valid(att_valid), .out(att_out), .out_head(att_head), .out_d(att_d));
    wire converted_valid, converted_last;
    q88_to_fp16_pipe u_result (.clk(clk), .rst_n(engine_rst_n),
        .in_valid(att_valid), .in_last(att_head == H-1 && att_d == D-1),
        .q88(att_out[31:16]), .fp16(out_fp16),
        .out_valid(converted_valid), .out_last(converted_last));
    assign out_valid = state == COLLECT && converted_valid;
    assign busy = state != IDLE;

    always @(posedge clk or negedge engine_rst_n) begin
        if (!engine_rst_n) begin
            state <= IDLE; pos_r <= 0; length_r <= 1; base_r <= 0;
            read_token <= 0; count <= 0; group_r <= 0; value_pass <= 0;
            done <= 0; error <= 0;
        end else begin
            done <= 0;
            case (state)
                IDLE: if (start) begin
                    error <= 0;
                    if (layer >= LAYERS || position >= MAX_T) begin
                        error <= 1; done <= 1;
                    end else begin
                        pos_r <= position[15:0]; length_r <= position[15:0]+16'd1;
                        base_r <= layer * MAX_T * TOKEN_BYTES;
                        state <= WRITE;
                    end
                end
                WRITE: state <= WRITE_WAIT;
                WRITE_WAIT: if (!kv_busy) begin
                    if (kv_error) begin error <= 1; done <= 1; state <= IDLE; end
                    else begin count <= 0; state <= ATT_START; end
                end
                ATT_START: state <= Q_FEED;
                Q_FEED: if (count == H*D-1) begin
                    count <= 0; group_r <= 0; value_pass <= 0; read_token <= 0;
                    state <= Q_DRAIN;
                end else count <= count+1'b1;
                Q_DRAIN: if(q_converted_valid && q_converted_last) state<=READ_CMD;
                READ_CMD: begin count <= 0; state <= READ_WORDS; end
                READ_WORDS: if (kv_valid) begin
                    if (count == D-1) begin
                        count <= 0;
                        if (kv_error) begin error <= 1; done <= 1; state <= IDLE; end
                        else state <= ROUTE;
                    end else count <= count+1'b1;
                end
                ROUTE: begin
                    count <= 0;
                    if (read_token == length_r-1) begin
                        read_token <= 0;
                        if (group_r == G-1) begin
                            group_r <= 0;
                            if (value_pass) state <= COLLECT;
                            else begin value_pass <= 1; state <= READ_CMD; end
                        end else begin group_r <= group_r+1'b1; state <= READ_CMD; end
                    end else begin read_token <= read_token+1'b1; state <= READ_CMD; end
                end
                COLLECT: if (converted_valid && converted_last) begin
                    done <= 1; state <= IDLE;
                end
            endcase
            if (state == READ_WORDS && kv_error && !kv_busy) begin
                error <= 1; done <= 1; state <= IDLE;
            end
        end
    end
endmodule


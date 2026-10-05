`timescale 1ns/1ps
// ============================================================================
// gqa_attention.v —— 分组查询注意力（GQA）头复用顶层
//
//   out[h] = attention(Q[h], K[g], V[g])，g = h / NGROUPS，NGROUPS = H/G
//
// 复用单头 attention 模块，逐头循环计算。SmolLM-135M：H=9, G=3, D=64。
// 输入顺序（各流用各自 valid）：先 Q（H×D），再 K（G×T×D），再 V（G×T×D）。
// 输出：H×D 个 out（head-major），out_valid + out + out_head + out_d。
// ============================================================================
module gqa_attention #(
    parameter H       = 4,     // 查询头数
    parameter G       = 2,     // KV 头数
    parameter D       = 4,     // head_dim
    parameter T       = 4,     // context 长度
    parameter DATA_W  = 16
)(
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire q_valid,
    input  wire signed [DATA_W-1:0] q_in,
    input  wire k_valid,
    input  wire signed [DATA_W-1:0] k_in,
    input  wire v_valid,
    input  wire signed [DATA_W-1:0] v_in,
    output reg  out_valid,
    output reg  signed [31:0] out,
    output reg  [7:0] out_head,   // 0..H-1
    output reg  [7:0] out_d       // 0..D-1
);
    localparam NGROUPS = H / G;
    localparam S_IDLE=4'd0, S_IN_Q=4'd1, S_IN_K=4'd2, S_IN_V=4'd3,
               S_HEAD=4'd4, S_FEED_Q=4'd5, S_FEED_K=4'd6, S_FEED_V=4'd7, S_COLLECT=4'd8;

    reg signed [DATA_W-1:0] q_ram [0:H-1][0:D-1];
    reg signed [DATA_W-1:0] k_ram [0:G-1][0:T-1][0:D-1];
    reg signed [DATA_W-1:0] v_ram [0:G-1][0:T-1][0:D-1];

    reg [3:0] state;
    reg [15:0] cnt;     // 通用计数器（输入/喂入元素计数，需覆盖 G*T*D=49152）
    reg [7:0] h_idx;
    reg [7:0] t_idx, d_idx;
    wire [7:0] g_idx = h_idx / NGROUPS;

    // 单头 attention（复用）
    reg att_start, att_q_valid, att_k_valid, att_v_valid;
    reg signed [DATA_W-1:0] att_q, att_k, att_v;
    wire att_out_valid;
    wire signed [31:0] att_out;
    attention #(.T(T), .D(D), .DATA_W(DATA_W)) u_att (
        .clk(clk), .rst_n(rst_n), .start(att_start),
        .q_valid(att_q_valid), .q_in(att_q),
        .k_valid(att_k_valid), .k_in(att_k),
        .v_valid(att_v_valid), .v_in(att_v),
        .out_valid(att_out_valid), .out(att_out)
    );

    integer i, j, k;
    initial begin
        for (i = 0; i < H; i = i + 1)
            for (j = 0; j < D; j = j + 1) q_ram[i][j] = 0;
        for (i = 0; i < G; i = i + 1)
            for (j = 0; j < T; j = j + 1)
                for (k = 0; k < D; k = k + 1) begin
                    k_ram[i][j][k] = 0; v_ram[i][j][k] = 0;
                end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; cnt <= 0; h_idx <= 0; t_idx <= 0; d_idx <= 0;
            out_valid <= 0; out <= 0; out_head <= 0; out_d <= 0;
            att_start <= 0; att_q_valid <= 0; att_k_valid <= 0; att_v_valid <= 0;
            att_q <= 0; att_k <= 0; att_v <= 0;
        end else begin
            out_valid <= 0;
            att_start <= 0; att_q_valid <= 0; att_k_valid <= 0; att_v_valid <= 0;
            case (state)
                S_IDLE: if (start) begin cnt <= 0; state <= S_IN_Q; end

                // ---- 输入 Q（H×D）----
                S_IN_Q: begin
                    if (q_valid) begin
                        q_ram[cnt / D][cnt % D] <= q_in;
                        if (cnt == H*D-1) begin cnt <= 0; state <= S_IN_K; end
                        else cnt <= cnt + 1'b1;
                    end
                end

                // ---- 输入 K（G×T×D）----
                S_IN_K: begin
                    if (k_valid) begin
                        k_ram[cnt/(T*D)][(cnt%(T*D))/D][cnt%D] <= k_in;
                        if (cnt == G*T*D-1) begin cnt <= 0; state <= S_IN_V; end
                        else cnt <= cnt + 1'b1;
                    end
                end

                // ---- 输入 V（G×T×D）----
                S_IN_V: begin
                    if (v_valid) begin
                        v_ram[cnt/(T*D)][(cnt%(T*D))/D][cnt%D] <= v_in;
                        if (cnt == G*T*D-1) begin cnt <= 0; h_idx <= 0; state <= S_HEAD; end
                        else cnt <= cnt + 1'b1;
                    end
                end

                // ---- 开始当前头的 attention ----
                S_HEAD: begin
                    att_start <= 1'b1;
                    cnt <= 0;
                    state <= S_FEED_Q;
                end

                // ---- 喂 Q[h]（D）----
                S_FEED_Q: begin
                    att_q_valid <= 1'b1;
                    att_q <= q_ram[h_idx][cnt];
                    if (cnt == D-1) begin cnt <= 0; state <= S_FEED_K; end
                    else cnt <= cnt + 1'b1;
                end

                // ---- 喂 K[g]（T×D）----
                S_FEED_K: begin
                    att_k_valid <= 1'b1;
                    att_k <= k_ram[g_idx][cnt/D][cnt%D];
                    if (cnt == T*D-1) begin cnt <= 0; state <= S_FEED_V; end
                    else cnt <= cnt + 1'b1;
                end

                // ---- 喂 V[g]（T×D）----
                S_FEED_V: begin
                    att_v_valid <= 1'b1;
                    att_v <= v_ram[g_idx][cnt/D][cnt%D];
                    if (cnt == T*D-1) begin cnt <= 0; state <= S_COLLECT; end
                    else cnt <= cnt + 1'b1;
                end

                // ---- 收 D 个输出 ----
                S_COLLECT: begin
                    if (att_out_valid) begin
                        out <= att_out;
                        out_head <= h_idx;
                        out_d <= cnt;
                        out_valid <= 1'b1;
                        if (cnt == D-1) begin
                            cnt <= 0;
                            if (h_idx == H-1) state <= S_IDLE;
                            else begin h_idx <= h_idx + 1'b1; state <= S_HEAD; end
                        end else cnt <= cnt + 1'b1;
                    end
                end
            endcase
        end
    end

endmodule

`timescale 1ns/1ps
// ============================================================================
// attention.v —— 单头注意力集成模块（先存后算）
//
//   scores[t] = dot(Q, K[t])           （QK 点积）
//   probs     = softmax(scores)        （max/exp LUT/sum/除法）
//   out[d]    = sum_t probs[t] * V[t][d] （PV 加权求和）
//
// 定点格式（CANDIDATE）：Q/K/V 为 Q8.8 有符号，probs Q0.16，out 32-bit。
// 输入顺序（每个流用各自 valid）：先 Q（D 个），再 K（T×D 个），再 V（T×D 个）。
// 输出：D 个 out（32-bit）。
// ============================================================================
module attention #(
    parameter T       = 4,     // context 长度
    parameter D       = 4,     // head_dim
    parameter DATA_W  = 16     // 元素位宽（Q8.8 有符号）
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
    output reg  signed [31:0] out
);
    localparam S_IDLE=4'd0, S_Q=4'd1, S_K=4'd2, S_V=4'd3,
               S_SCORE=4'd4, S_SM_MAX=4'd5, S_SM_EXP=4'd6, S_SM_DIV=4'd7, S_OUT=4'd8;

    reg signed [DATA_W-1:0] q_ram [0:D-1];
    reg signed [DATA_W-1:0] k_ram [0:T-1][0:D-1];
    reg signed [DATA_W-1:0] v_ram [0:T-1][0:D-1];
    reg signed [31:0] scores [0:T-1];   // 后复用作 exp 值
    reg [15:0] probs [0:T-1];

    reg [3:0] state;
    reg [7:0] t_idx, d_idx;
    reg signed [31:0] max_r;            // Q16.16
    reg [31:0] sum_r;
    reg signed [39:0] acc;              // 点积累加器
    reg signed [31:0] out_acc;

    // exp 查找表：score 为 Q16.16，先 >>8 到 Q8.8，再 >>3 得 LUT 地址，即 >>11
    wire [31:0] neg_x   = max_r - scores[t_idx];                 // >= 0
    wire [7:0]  lut_addr = (neg_x > 32'd522240) ? 8'd255 : neg_x[18:11];
    wire [15:0] lut_val;
    exp_lut u_lut (.addr(lut_addr), .val(lut_val));

    // 除法器
    reg div_start;
    reg div_busy;                 // 跟踪除法进行中
    reg [31:0] div_num;
    wire div_done;
    wire [31:0] div_quot;
    div_u32_u32 u_div (
        .clk(clk), .rst_n(rst_n), .start(div_start),
        .numerator(div_num), .denominator(sum_r),
        .done(div_done), .quotient(div_quot), .remainder()
    );

    integer i, j;
    initial begin
        for (i = 0; i < D; i = i + 1) q_ram[i] = 0;
        for (i = 0; i < T; i = i + 1) begin
            for (j = 0; j < D; j = j + 1) begin
                k_ram[i][j] = 0; v_ram[i][j] = 0;
            end
            scores[i] = 0; probs[i] = 0;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; t_idx <= 0; d_idx <= 0; max_r <= 0; sum_r <= 0;
            acc <= 0; out_acc <= 0; out_valid <= 0; out <= 0;
            div_start <= 0; div_busy <= 0; div_num <= 0;
        end else begin
            out_valid <= 0;
            div_start <= 0;
            case (state)
                S_IDLE: if (start) begin d_idx <= 0; state <= S_Q; end

                S_Q: begin
                    if (q_valid) begin
                        q_ram[d_idx] <= q_in;
                        if (d_idx == D-1) begin d_idx <= 0; t_idx <= 0; state <= S_K; end
                        else d_idx <= d_idx + 1'b1;
                    end
                end

                S_K: begin
                    if (k_valid) begin
                        k_ram[t_idx][d_idx] <= k_in;
                        if (d_idx == D-1) begin
                            d_idx <= 0;
                            if (t_idx == T-1) begin t_idx <= 0; state <= S_V; end
                            else t_idx <= t_idx + 1'b1;
                        end else d_idx <= d_idx + 1'b1;
                    end
                end

                S_V: begin
                    if (v_valid) begin
                        v_ram[t_idx][d_idx] <= v_in;
                        if (d_idx == D-1) begin
                            d_idx <= 0;
                            if (t_idx == T-1) begin t_idx <= 0; acc <= 0; state <= S_SCORE; end
                            else t_idx <= t_idx + 1'b1;
                        end else d_idx <= d_idx + 1'b1;
                    end
                end

                S_SCORE: begin
                    acc <= acc + ($signed(q_ram[d_idx]) * $signed(k_ram[t_idx][d_idx]));
                    if (d_idx == D-1) begin
                        scores[t_idx] <= acc + ($signed(q_ram[d_idx]) * $signed(k_ram[t_idx][d_idx]));
                        d_idx <= 0;
                        if (t_idx == T-1) begin t_idx <= 0; max_r <= 32'sh80000000; state <= S_SM_MAX; end
                        else begin t_idx <= t_idx + 1'b1; acc <= 0; end
                    end else d_idx <= d_idx + 1'b1;
                end

                S_SM_MAX: begin
                    if (scores[t_idx] > max_r) max_r <= scores[t_idx];
                    if (t_idx == T-1) begin t_idx <= 0; sum_r <= 0; state <= S_SM_EXP; end
                    else t_idx <= t_idx + 1'b1;
                end

                S_SM_EXP: begin
                    scores[t_idx] <= lut_val;          // 存回 exp
                    sum_r <= sum_r + lut_val;
                    if (t_idx == T-1) begin t_idx <= 0; state <= S_SM_DIV; end
                    else t_idx <= t_idx + 1'b1;
                end

                S_SM_DIV: begin
                    if (!div_busy) begin
                        div_num   <= {scores[t_idx][15:0], 16'd0};   // e << 16
                        div_start <= 1'b1;
                        div_busy  <= 1'b1;
                    end else if (div_done) begin
                        probs[t_idx] <= (div_quot > 32'd65535) ? 16'd65535 : div_quot[15:0];
                        div_busy    <= 1'b0;
                        if (t_idx == T-1) begin t_idx <= 0; d_idx <= 0; out_acc <= 0; state <= S_OUT; end
                        else begin t_idx <= t_idx + 1'b1; end
                    end
                end

                S_OUT: begin
                    // out[d] = sum_t probs[t]*V[t][d]：d 外层，t 内层
                    out_acc <= out_acc + ($signed({1'b0, probs[t_idx]}) * $signed(v_ram[t_idx][d_idx]));
                    if (t_idx == T-1) begin
                        out <= out_acc + ($signed({1'b0, probs[t_idx]}) * $signed(v_ram[t_idx][d_idx]));
                        out_valid <= 1'b1;
                        t_idx <= 0;
                        if (d_idx == D-1) begin state <= S_IDLE; end
                        else begin d_idx <= d_idx + 1'b1; out_acc <= 0; end
                    end else t_idx <= t_idx + 1'b1;
                end
            endcase
        end
    end

endmodule

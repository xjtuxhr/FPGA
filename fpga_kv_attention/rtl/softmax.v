`timescale 1ns/1ps
// ============================================================================
// softmax.v —— 完整 softmax（使用校准 exp LUT + 32/32 除法器）
//
//   p_i = exp(s_i - max) / sum_j exp(s_j - max)
//
// 定点格式（CANDIDATE，NUM-003）：
//   score 输入 Q8.8 有符号；prob 输出 Q0.16 无符号（sum = 65536）
//
// 三遍扫描：
//   1) S_MAX：流式输入 T 个 score，找 max，存 RAM；
//   2) S_EXP：读 RAM 算 exp(max-score)（经 exp_lut 查表），存回 RAM 并累加 sum；
//   3) S_DIV：读 RAM，p = (e << 16) / sum，经 div_u32_u32 逐项输出。
// ============================================================================
module softmax #(
    parameter T       = 64,     // 序列长度
    parameter SCORE_W = 16      // score 位宽（Q8.8）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire start,                        // 序列开始脉冲
    input  wire valid_in,
    input  wire signed [SCORE_W-1:0] score,
    output reg  valid_out,
    output reg  [15:0] prob                  // Q0.16
);
    localparam S_IDLE = 3'd0, S_MAX = 3'd1, S_EXP = 3'd2,
               S_DIV_START = 3'd3, S_DIV_WAIT = 3'd4;

    reg [15:0] ram [0:T-1];                    // 先存 score，后存 exp
    reg signed [SCORE_W-1:0] max_r;
    reg [31:0] sum_r;
    reg [7:0] idx;                             // 0..T-1（T<=256）
    reg [2:0] state;

    // exp 查找表
    wire [7:0] lut_addr;
    wire [15:0] lut_val;
    exp_lut u_lut (.addr(lut_addr), .val(lut_val));

    // 32/32 除法器
    reg  div_start;
    reg  [31:0] div_num;
    wire div_done;
    wire [31:0] div_quot;
    div_u32_u32 u_div (
        .clk(clk), .rst_n(rst_n), .start(div_start),
        .numerator(div_num), .denominator(sum_r),
        .done(div_done), .quotient(div_quot), .remainder()
    );

    // 组合：exp 输入的地址 = (max - score) >> 3，clamp 到 [0,255]
    wire [15:0] neg_x = $unsigned(max_r) - ram[idx];
    assign lut_addr = (neg_x > 16'd2040) ? 8'd255 : neg_x[10:3];

    integer i;
    initial begin
        for (i = 0; i < T; i = i + 1) ram[i] = 16'd0;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            max_r     <= 16'sh8000;   // -32768
            sum_r     <= 32'd0;
            idx       <= 8'd0;
            valid_out <= 1'b0;
            prob      <= 16'd0;
            div_start <= 1'b0;
            div_num   <= 32'd0;
        end else begin
            valid_out <= 1'b0;
            div_start <= 1'b0;
            case (state)
                S_IDLE: begin
                    if (start) begin
                        max_r <= 16'sh8000;
                        idx   <= 8'd0;
                        state <= S_MAX;
                    end
                end
                S_MAX: begin
                    if (valid_in) begin
                        ram[idx] <= score;
                        if (score > max_r) max_r <= score;
                        if (idx == T - 1) begin idx <= 8'd0; sum_r <= 32'd0; state <= S_EXP; end
                        else idx <= idx + 1'b1;
                    end
                end
                S_EXP: begin
                    ram[idx] <= lut_val;                 // 存回 exp
                    sum_r    <= sum_r + lut_val;
                    if (idx == T - 1) begin idx <= 8'd0; state <= S_DIV_START; end
                    else idx <= idx + 1'b1;
                end
                S_DIV_START: begin
                    div_num   <= {ram[idx], 16'd0};      // e << 16
                    div_start <= 1'b1;
                    state     <= S_DIV_WAIT;
                end
                S_DIV_WAIT: begin
                    if (div_done) begin
                        prob      <= (div_quot > 32'd65535) ? 16'd65535 : div_quot[15:0];
                        valid_out <= 1'b1;
                        if (idx == T - 1) state <= S_IDLE;
                        else begin idx <= idx + 1'b1; state <= S_DIV_START; end
                    end
                end
            endcase
        end
    end

endmodule

`timescale 1ns/1ps
// ============================================================================
// dot_product.v —— 向量点积（attention 的 QK score 计算）
//
//   score = sum_{d=0}^{LEN-1} a[d] * b[d]
//
// 用途：QKᵀ —— a = query 向量，b = key 向量，score 即注意力分数。
// 定点格式（CANDIDATE，对应 NUM-002 未冻结）：
//   a/b 为 Q8.8 有符号；score 输出 32-bit（宽累加器取低 32 位）。
//
// 接口：valid_in=1 时逐元素输入 a/b，LEN 个元素后给出 valid_out + result。
// ============================================================================
module dot_product #(
    parameter LEN    = 64,     // 向量长度（head_dim）
    parameter DATA_W = 16      // 元素位宽（Q8.8 有符号）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire valid_in,
    input  wire signed [DATA_W-1:0] a,
    input  wire signed [DATA_W-1:0] b,
    output reg  valid_out,          // result 有效脉冲
    output reg  signed [31:0] result
);
    reg [6:0] cnt;
    reg signed [39:0] acc;          // 宽累加器（LEN 个 DATA_W*DATA_W 乘积之和）

    wire signed [39:0] next_acc = acc + $signed(a) * $signed(b);
    wire is_last = (cnt == LEN - 1);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt       <= 7'd0;
            acc       <= 40'sd0;
            valid_out <= 1'b0;
            result    <= 32'sd0;
        end else begin
            valid_out <= 1'b0;
            if (valid_in) begin
                if (is_last) begin
                    result    <= next_acc[31:0];   // 含最后一个元素
                    valid_out <= 1'b1;
                    cnt       <= 7'd0;
                    acc       <= 40'sd0;
                end else begin
                    acc <= next_acc;
                    cnt <= cnt + 1'b1;
                end
            end
        end
    end

endmodule

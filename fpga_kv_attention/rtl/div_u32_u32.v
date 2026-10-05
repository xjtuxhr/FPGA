`timescale 1ns/1ps
// ============================================================================
// div_u32_u32.v —— 32/32 无符号除法（恢复余数法，32 拍）
//   quotient = numerator / denominator（floor），remainder = 余数
// 用于 softmax 的归一化：p = (e << 16) / sum。
// ============================================================================
module div_u32_u32 (
    input  wire clk,
    input  wire rst_n,
    input  wire start,
    input  wire [31:0] numerator,
    input  wire [31:0] denominator,
    output reg  done,
    output reg  [31:0] quotient,
    output reg  [31:0] remainder
);
    reg [31:0] rem;
    reg [31:0] quot;
    reg [5:0] bit;               // 0..32
    reg busy;
    reg [31:0] num_r, den_r;

    wire [31:0] rem_shift = {rem[30:0], num_r[bit-1]};
    wire [32:0] rem_sub   = {1'b0, rem_shift} - {1'b0, den_r};
    wire neg = rem_sub[32];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy <= 0; done <= 0; quotient <= 0; remainder <= 0;
            rem <= 0; quot <= 0; bit <= 0; num_r <= 0; den_r <= 0;
        end else begin
            done <= 0;
            if (!busy && start) begin
                num_r <= numerator; den_r <= denominator;
                rem <= 0; quot <= 0; bit <= 6'd32; busy <= 1;
            end else if (busy) begin
                if (bit > 0) begin
                    if (neg) begin
                        rem  <= rem_sub[31:0] + den_r;
                        quot <= {quot[30:0], 1'b0};
                    end else begin
                        rem  <= rem_sub[31:0];
                        quot <= {quot[30:0], 1'b1};
                    end
                    bit <= bit - 1'b1;
                end else begin
                    quotient <= quot; remainder <= rem; done <= 1; busy <= 0;
                end
            end
        end
    end

endmodule

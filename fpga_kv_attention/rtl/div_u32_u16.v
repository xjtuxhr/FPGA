`timescale 1ns/1ps
// ============================================================================
// div_u32_u16.v —— 32/16 无符号除法（恢复余数法，32 拍）
//
//   quotient = numerator / denominator（floor），remainder = 余数
//
// 处理完整的 32 位被除数（从 bit31 逐位到 bit0），商为 32 位、取低 16 位输出。
// 用于 KVmix 的 scale 计算：inv_scale = (qmax << 16) / span。
// ============================================================================
module div_u32_u16 (
    input  wire clk,
    input  wire rst_n,
    input  wire start,           // 启动脉冲
    input  wire [31:0] numerator,
    input  wire [15:0] denominator,
    output reg  done,            // 完成脉冲
    output reg  [15:0] quotient,
    output reg  [15:0] remainder
);
    reg [31:0] rem;
    reg [31:0] quot;             // 32 位商
    reg [5:0] bit;               // 0..32
    reg busy;
    reg [31:0] num_r;
    reg [15:0] den_r;

    // 组合：rem 左移 + 当前被除数位，再减除数
    wire [31:0] rem_shift = {rem[30:0], num_r[bit-1]};
    wire [32:0] rem_sub   = {1'b0, rem_shift} - {17'd0, den_r};
    wire neg = rem_sub[32];      // 借位 = 结果为负

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy      <= 1'b0;
            done      <= 1'b0;
            quotient  <= 16'd0;
            remainder <= 16'd0;
            rem       <= 32'd0;
            quot      <= 32'd0;
            bit       <= 6'd0;
            num_r     <= 32'd0;
            den_r     <= 16'd0;
        end else begin
            done <= 1'b0;
            if (!busy && start) begin
                num_r <= numerator;
                den_r <= denominator;
                rem   <= 32'd0;
                quot  <= 32'd0;
                bit   <= 6'd32;
                busy  <= 1'b1;
            end else if (busy) begin
                if (bit > 0) begin
                    if (neg) begin
                        rem  <= rem_sub[31:0] + den_r;   // 恢复余数
                        quot <= {quot[30:0], 1'b0};
                    end else begin
                        rem  <= rem_sub[31:0];
                        quot <= {quot[30:0], 1'b1};
                    end
                    bit <= bit - 1'b1;
                end else begin
                    quotient  <= quot[15:0];   // 取低 16 位（商在 16 位内）
                    remainder <= rem[15:0];
                    done      <= 1'b1;
                    busy      <= 1'b0;
                end
            end
        end
    end

endmodule

`timescale 1ns/1ps
// ============================================================================
// kv_pack_3bit.v —— KVmix 3-bit 特例打包
//
// 论文的 3-bit 打包：11 个元素打包成 1 个 32-bit 字
//   前 10 个元素各 3-bit（0..7），第 11 个元素 2-bit（0..3）
//   位布局：q[0] 在 bit0..2，q[1] 在 bit3..5，...，q[9] 在 bit27..29，q[10] 在 bit30..31
//   （10×3 + 1×2 = 32 bit，正好一个 int32，不跨字）
//
// 接口：valid_in/q_in 逐个输入 11 个量化值，第 11 个输入时输出完整 packed 字
// ============================================================================
module kv_pack_3bit (
    input  wire clk,
    input  wire rst_n,
    input  wire valid_in,
    input  wire [3:0] q_in,        // 量化值（前10个 0..7，第11个只取低2位 0..3）
    output reg  valid_out,         // 打包完成脉冲
    output reg  [31:0] packed      // 打包结果
);
    reg [3:0] cnt;                 // 0..10
    reg [31:0] packed_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt       <= 4'd0;
            packed_r  <= 32'd0;
            valid_out <= 1'b0;
            packed    <= 32'd0;
        end else begin
            valid_out <= 1'b0;
            if (valid_in) begin
                if (cnt == 4'd10) begin
                    // 第 11 个元素（2-bit）放 bit30..31，输出完整字并复位
                    packed    <= packed_r | ({30'd0, q_in[1:0]} << 30);
                    valid_out <= 1'b1;
                    packed_r  <= 32'd0;
                    cnt       <= 4'd0;
                end else begin
                    // 前 10 个元素（3-bit）依次放 cnt*3 位
                    packed_r <= packed_r | ({29'd0, q_in[2:0]} << (cnt * 3));
                    cnt      <= cnt + 1'b1;
                end
            end
        end
    end

endmodule

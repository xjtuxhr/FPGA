`timescale 1ns/1ps
// ============================================================================
// kv_unpack_3bit.v —— KVmix 3-bit 特例解包
//
// 1 个 32-bit 字 → 11 个元素（前 10 个 3-bit，第 11 个 2-bit）
// 与 kv_pack_3bit 互逆。
// ============================================================================
module kv_unpack_3bit (
    input  wire clk,
    input  wire rst_n,
    input  wire valid_in,          // 新 packed 字到达脉冲
    input  wire [31:0] packed,
    output reg  valid_out,         // 每个解包值输出脉冲
    output reg  [3:0] q_out,       // 0..7（第 11 个是 0..3）
    output reg  [3:0] pos          // 0..10
);
    reg [31:0] packed_r;           // 锁存的 packed 字
    reg [3:0] cnt;
    reg busy;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            packed_r  <= 32'd0;
            cnt       <= 4'd0;
            busy      <= 1'b0;
            valid_out <= 1'b0;
            q_out     <= 4'd0;
            pos       <= 4'd0;
        end else begin
            valid_out <= 1'b0;
            if (!busy && valid_in) begin
                // 锁存新字，开始解包
                packed_r <= packed;
                cnt      <= 4'd0;
                busy     <= 1'b1;
            end else if (busy) begin
                // 逐元素输出
                if (cnt < 4'd10)
                    q_out <= (packed_r >> (cnt * 3)) & 4'b111;   // 3-bit
                else
                    q_out <= {2'b00, packed_r[31:30]};           // 2-bit
                pos       <= cnt;
                valid_out <= 1'b1;
                if (cnt == 4'd10) begin
                    busy <= 1'b0;
                    cnt  <= 4'd0;
                end else begin
                    cnt  <= cnt + 1'b1;
                end
            end
        end
    end

endmodule

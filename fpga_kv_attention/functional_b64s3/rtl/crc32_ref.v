`timescale 1ns/1ps
// ============================================================================
// crc32_ref.v —— CRC-32/ISO-HDLC（= zlib.crc32），反射多项式 0xEDB88320
//
// 流式：每拍处理 128-bit（16 字节，低字节 data[7:0] 在前），init 复位到 0xFFFFFFFF。
// check："123456789" -> 0xCBF43926。用于 v2 endpoint 的请求校验 + 响应生成。
// ============================================================================
module crc32_ref (
    input  wire clk,
    input  wire rst_n,
    input  wire init,           // 脉冲：复位 crc 到 0xFFFFFFFF
    input  wire valid,          // 数据有效
    input  wire [127:0] data,   // 16 字节（低字节在前）
    output wire [31:0] crc      // 最终 CRC（= 运行值 ^ 0xFFFFFFFF，即 zlib.crc32）
);
    reg [31:0] crc_r;           // 运行 CRC（init 0xFFFFFFFF，无 xorout）
    // 单字节更新（反射）
    function [31:0] crc_byte;
        input [31:0] c;
        input [7:0]  b;
        integer i;
        reg [31:0] r;
        begin
            r = c ^ {24'd0, b};
            for (i = 0; i < 8; i = i + 1) begin
                if (r[0]) r = (r >> 1) ^ 32'hEDB88320;
                else      r = r >> 1;
            end
            crc_byte = r;
        end
    endfunction

    // INIT+VALID starts a new frame and includes its first beat. This avoids
    // an idle-cycle dependency for back-to-back frames.
    wire [31:0] n0  = crc_byte(init ? 32'hFFFFFFFF : crc_r, data[7:0]);
    wire [31:0] n1  = crc_byte(n0,  data[15:8]);
    wire [31:0] n2  = crc_byte(n1,  data[23:16]);
    wire [31:0] n3  = crc_byte(n2,  data[31:24]);
    wire [31:0] n4  = crc_byte(n3,  data[39:32]);
    wire [31:0] n5  = crc_byte(n4,  data[47:40]);
    wire [31:0] n6  = crc_byte(n5,  data[55:48]);
    wire [31:0] n7  = crc_byte(n6,  data[63:56]);
    wire [31:0] n8  = crc_byte(n7,  data[71:64]);
    wire [31:0] n9  = crc_byte(n8,  data[79:72]);
    wire [31:0] n10 = crc_byte(n9,  data[87:80]);
    wire [31:0] n11 = crc_byte(n10, data[95:88]);
    wire [31:0] n12 = crc_byte(n11, data[103:96]);
    wire [31:0] n13 = crc_byte(n12, data[111:104]);
    wire [31:0] n14 = crc_byte(n13, data[119:112]);
    wire [31:0] n15 = crc_byte(n14, data[127:120]);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)        crc_r <= 32'hFFFFFFFF;
        else if (init)     crc_r <= valid ? n15 : 32'hFFFFFFFF;
        else if (valid)    crc_r <= n15;
    end

    assign crc = crc_r ^ 32'hFFFFFFFF;   // xorout
endmodule

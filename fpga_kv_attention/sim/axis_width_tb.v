`timescale 1ns/1ps
// axis_width_tb.v —— 128<->16 宽度转换 roundtrip 自校验
// 128to16 -> 16to128 串接。逐拍「喂 -> 等输出 -> 比对」，避免流水线导致的失步。
module axis_width_tb;
    reg clk = 0, rst_n = 0;
    reg s_valid = 0;
    reg [127:0] s_data = 0;
    reg [15:0] s_keep = 16'hFFFF;
    reg s_last = 0;
    wire s_ready;
    wire m16_valid, m16_last;
    wire [15:0] m16_data;
    wire m16_ready;
    wire m128_valid, m128_last;
    wire [127:0] m128_data;
    wire [15:0] m128_keep;
    reg m128_ready = 1'b1;

    axis_128to16 u1 (.clk(clk), .rst_n(rst_n), .s_valid(s_valid), .s_data(s_data),
        .s_keep(s_keep), .s_last(s_last), .s_ready(s_ready),
        .m_valid(m16_valid), .m_data(m16_data), .m_last(m16_last), .m_ready(m16_ready));

    axis_16to128 u2 (.clk(clk), .rst_n(rst_n), .s_valid(m16_valid), .s_data(m16_data),
        .s_last(m16_last), .s_ready(m16_ready),
        .m_valid(m128_valid), .m_data(m128_data), .m_keep(m128_keep), .m_last(m128_last),
        .m_ready(m128_ready));

    always #5 clk = ~clk;

    integer i, errors = 0;
    reg [127:0] expect [0:2];

    initial begin
        #20 rst_n = 1'b1; #10;

        // 3 拍 128-bit，每拍 = 8 个 16-bit 元素（低 16 位在前）
        expect[0] = 128'h00070006000500040003000200010000;  // 元素 0..7
        expect[1] = 128'h000F000E000D000C000B000A00090008;  // 元素 8..15
        expect[2] = 128'h00170016001500140013001200110010;  // 元素 16..23

        for (i = 0; i < 3; i = i + 1) begin
            // 喂一拍（链路此时应空闲，s_ready=1）
            @(negedge clk);
            s_valid = 1'b1; s_data = expect[i]; s_last = (i == 2);
            @(posedge clk);          // 接受
            @(negedge clk);
            s_valid = 1'b0;
            // 等这一拍的输出并比对
            while (!m128_valid) @(posedge clk);
            @(negedge clk);
            if (m128_data !== expect[i] || m128_last !== (i == 2)) begin
                errors = errors + 1;
                $display("FAIL out beat %0d: %h last=%0d (expect %h)", i, m128_data, m128_last, expect[i]);
            end
        end

        if (errors == 0) $display("axis_width: ALL checks PASSED");
        else $display("axis_width: %0d ERRORS", errors);
        $finish;
    end
endmodule

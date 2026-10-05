`timescale 1ns/1ps
// axis_fifo_tb.v —— AXI-ST FIFO 自校验（小深度 DEPTH=16）
// 写满 -> 满标志 -> 读空并校验 data/last -> 空标志 -> 背压保持。
module axis_fifo_tb;
    parameter DEPTH = 16, DATA_W = 16, ADDR_W = 4;
    reg clk = 0, rst_n = 0;
    reg s_valid = 0, s_last = 0, m_ready = 0;
    reg [15:0] s_data = 0;
    wire s_ready, m_valid, m_last;
    wire [15:0] m_data;

    axis_fifo #(.DEPTH(DEPTH), .DATA_W(DATA_W), .ADDR_W(ADDR_W)) dut (
        .clk(clk), .rst_n(rst_n),
        .s_valid(s_valid), .s_data(s_data), .s_last(s_last), .s_ready(s_ready),
        .m_valid(m_valid), .m_data(m_data), .m_last(m_last), .m_ready(m_ready));

    always #5 clk = ~clk;

    integer i, errors = 0;

    initial begin
        #20 rst_n = 1'b1; #10;

        // ---- 1) 写满 DEPTH 个字 ----
        for (i = 0; i < DEPTH; i = i + 1) begin
            @(negedge clk);
            s_valid = 1'b1; s_data = i[15:0]; s_last = (i == DEPTH-1);
        end
        @(negedge clk); s_valid = 1'b0; s_last = 1'b0;
        @(posedge clk); #1;
        if (s_ready) begin errors = errors + 1; $display("FAIL not full"); end

        // ---- 2) 读空，校验 data + last ----
        for (i = 0; i < DEPTH; i = i + 1) begin
            @(negedge clk);
            m_ready = 1'b1;
            #1;
            if (!m_valid || m_data !== i[15:0] || m_last !== (i == DEPTH-1)) begin
                errors = errors + 1;
                if (errors <= 10)
                    $display("FAIL rd@%0d: valid=%0d data=%0d last=%0d", i, m_valid, m_data, m_last);
            end
        end
        @(negedge clk); m_ready = 1'b0;
        @(posedge clk); #1;
        if (m_valid) begin errors = errors + 1; $display("FAIL not empty"); end

        // ---- 3) 背压：写 3 字，读侧不读，数据应保持 ----
        @(negedge clk); s_valid = 1'b1; s_data = 100;
        @(negedge clk); s_data = 101;
        @(negedge clk); s_data = 102;
        @(negedge clk); s_valid = 1'b0;
        @(posedge clk); #1;
        if (!m_valid || m_data !== 100) begin errors = errors + 1; $display("FAIL bp first word"); end
        @(negedge clk); @(negedge clk); @(negedge clk);   // 3 拍不读
        #1;
        if (!m_valid || m_data !== 100) begin errors = errors + 1; $display("FAIL bp hold"); end

        if (errors == 0) $display("axis_fifo: ALL checks PASSED");
        else $display("axis_fifo: %0d ERRORS", errors);
        $finish;
    end
endmodule

`timescale 1ns/1ps
// usr_loopback_tb.v —— H2C->C2H 回环自校验
// 喂 2 拍 128-bit，收 2 拍，比对 data/keep/last 一致。
module usr_loopback_tb;
    reg clk = 0, rst_n = 0;
    reg [127:0] h2c_tdata = 0;
    reg [15:0]  h2c_tkeep = 16'hFFFF;
    reg [15:0]  h2c_tuser = 0;
    reg         h2c_tlast = 0, h2c_tvalid = 0;
    wire        h2c_tready;
    wire [127:0] c2h_tdata;
    wire [15:0]  c2h_tkeep, c2h_tuser;
    wire         c2h_tlast, c2h_tvalid;
    reg          c2h_tready = 1'b1;

    usr_loopback dut (
        .clk(clk), .rst_n(rst_n),
        .m0_axis_h2c_tdata(h2c_tdata), .m0_axis_h2c_tkeep(h2c_tkeep),
        .m0_axis_h2c_tuser(h2c_tuser), .m0_axis_h2c_tlast(h2c_tlast),
        .m0_axis_h2c_tvalid(h2c_tvalid), .m0_axis_h2c_tready(h2c_tready),
        .s0_axis_c2h_tdata(c2h_tdata), .s0_axis_c2h_tkeep(c2h_tkeep),
        .s0_axis_c2h_tuser(c2h_tuser), .s0_axis_c2h_tlast(c2h_tlast),
        .s0_axis_c2h_tvalid(c2h_tvalid), .s0_axis_c2h_tready(c2h_tready));

    always #5 clk = ~clk;

    integer i, errors = 0;
    reg [127:0] expect [0:1];

    initial begin
        #20 rst_n = 1'b1; #10;

        expect[0] = 128'h00070006000500040003000200010000;
        expect[1] = 128'h000F000E000D000C000B000A00090008;

        for (i = 0; i < 2; i = i + 1) begin
            @(negedge clk);
            h2c_tvalid = 1'b1; h2c_tdata = expect[i]; h2c_tkeep = 16'hFFFF; h2c_tlast = (i == 1);
            @(posedge clk);
            @(negedge clk);
            h2c_tvalid = 1'b0;
            // 等回环输出；FIFO 的 m_data 是组合逻辑（mem[rptr]），C2H 常 ready 会当拍排空，
            // 所以要在 c2h_tvalid=1 的同一拍采样，不能等到下一拍。
            while (!c2h_tvalid) @(posedge clk);
            if (c2h_tdata !== expect[i] || c2h_tkeep !== 16'hFFFF || c2h_tlast !== (i == 1)) begin
                errors = errors + 1;
                $display("FAIL beat %0d: data=%h keep=%h last=%0d", i, c2h_tdata, c2h_tkeep, c2h_tlast);
            end
        end

        if (errors == 0) $display("usr_loopback: ALL checks PASSED");
        else $display("usr_loopback: %0d ERRORS", errors);
        $finish;
    end
endmodule

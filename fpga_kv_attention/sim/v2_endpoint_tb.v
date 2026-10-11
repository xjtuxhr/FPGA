`timescale 1ns/1ps
// v2_endpoint_tb.v —— v2 endpoint 自校验（对拍 contract.py 的 request/response）
module v2_endpoint_tb;
    reg clk = 0, rst_n = 0;
    reg [127:0] h2c_tdata = 0;
    reg h2c_tlast = 0, h2c_tvalid = 0;
    wire h2c_tready;
    wire [127:0] c2h_tdata;
    wire [15:0] c2h_tkeep, c2h_tuser;
    wire c2h_tlast, c2h_tvalid;
    reg c2h_tready = 1'b1;

    v2_endpoint dut (
        .clk(clk), .rst_n(rst_n),
        .m0_axis_h2c_tdata(h2c_tdata), .m0_axis_h2c_tkeep(16'hFFFF),
        .m0_axis_h2c_tuser(16'd0), .m0_axis_h2c_tlast(h2c_tlast),
        .m0_axis_h2c_tvalid(h2c_tvalid), .m0_axis_h2c_tready(h2c_tready),
        .s0_axis_c2h_tdata(c2h_tdata), .s0_axis_c2h_tkeep(c2h_tkeep),
        .s0_axis_c2h_tuser(c2h_tuser), .s0_axis_c2h_tlast(c2h_tlast),
        .s0_axis_c2h_tvalid(c2h_tvalid), .s0_axis_c2h_tready(c2h_tready));

    reg [15:0] vec [0:16383];
    integer idx, nc, ci, bi, wi, errors = 0;
    integer n_req, n_resp;
    reg [127:0] beat;
    reg [127:0] exp_resp [0:1023];

    always #5 clk = ~clk;

    task feed_beat(input [127:0] d, input last);
        begin
            @(negedge clk); h2c_tvalid = 1'b1; h2c_tdata = d; h2c_tlast = last;
            @(posedge clk);
            @(negedge clk); h2c_tvalid = 1'b0;
        end
    endtask

    initial begin
        $readmemh("golden/v2_endpoint.hex", vec);
        nc = vec[0]; idx = 1;
        #20 rst_n = 1'b1; #10;

        for (ci = 0; ci < nc; ci = ci + 1) begin
            n_req = vec[idx]; idx = idx + 1;
            for (bi = 0; bi < n_req; bi = bi + 1) begin
                beat = 128'd0;
                for (wi = 0; wi < 8; wi = wi + 1) begin
                    beat = beat | ({112'd0, vec[idx]} << (16*wi)); idx = idx + 1;
                end
                feed_beat(beat, (bi == n_req-1));
            end
            // 读期望响应
            n_resp = vec[idx]; idx = idx + 1;
            for (bi = 0; bi < n_resp; bi = bi + 1) begin
                exp_resp[bi] = 128'd0;
                for (wi = 0; wi < 8; wi = wi + 1) begin
                    exp_resp[bi] = exp_resp[bi] | ({112'd0, vec[idx]} << (16*wi)); idx = idx + 1;
                end
            end
            // 收响应并比对（posedge 当拍采样，tvalid && tready 才是一拍）
            bi = 0;
            while (bi < n_resp) begin
                @(posedge clk);
                if (c2h_tvalid && c2h_tready) begin
                    if (c2h_tdata !== exp_resp[bi] || c2h_tlast !== (bi == n_resp-1)) begin
                        errors = errors + 1;
                        if (errors <= 5)
                            $display("FAIL case %0d beat %0d: %h last=%0d (expect %h last=%0d)",
                                     ci, bi, c2h_tdata, c2h_tlast, exp_resp[bi], (bi == n_resp-1));
                    end
                    bi = bi + 1;
                end
            end
        end

        if (errors == 0) $display("v2_endpoint: ALL %0d cases PASSED", nc);
        else $display("v2_endpoint: %0d ERRORS", errors);
        $finish;
    end
endmodule

`timescale 1ns/1ps
// crc32_ref_tb.v —— CRC-32/ISO-HDLC 自校验（对拍 zlib.crc32）
module crc32_ref_tb;
    reg clk = 0, rst_n = 0, init = 0, valid = 0;
    reg [127:0] data = 0;
    wire [31:0] crc;
    crc32_ref dut (.clk(clk), .rst_n(rst_n), .init(init), .valid(valid), .data(data), .crc(crc));

    reg [15:0] vec [0:4095];
    integer nc, ci, bi, wi, errors = 0;
    integer idx, nbeats;
    reg [127:0] beat;
    reg [31:0] expect;

    always #5 clk = ~clk;

    task feed_beat(input [127:0] d);
        begin
            @(negedge clk); valid = 1'b1; data = d;
            @(posedge clk);
            @(negedge clk); valid = 1'b0;
        end
    endtask

    initial begin
        $readmemh("golden/crc32.hex", vec);
        nc = vec[0];
        idx = 1;
        #20 rst_n = 1'b1; #10;

        for (ci = 0; ci < nc; ci = ci + 1) begin
            nbeats = vec[idx]; idx = idx + 1;
            @(negedge clk); init = 1'b1;
            @(posedge clk);
            @(negedge clk); init = 1'b0;
            for (bi = 0; bi < nbeats; bi = bi + 1) begin
                beat = 128'd0;
                for (wi = 0; wi < 8; wi = wi + 1) begin
                    beat = beat | ({112'd0, vec[idx]} << (16*wi));
                    idx = idx + 1;
                end
                feed_beat(beat);
            end
            expect = {vec[idx+1], vec[idx]}; idx = idx + 2;
            #1;
            if (crc !== expect) begin
                errors = errors + 1;
                $display("FAIL case %0d: crc=%08x expect %08x", ci, crc, expect);
            end
        end

        if (errors == 0) $display("crc32_ref: ALL %0d cases PASSED", nc);
        else $display("crc32_ref: %0d ERRORS", errors);
        $finish;
    end
endmodule

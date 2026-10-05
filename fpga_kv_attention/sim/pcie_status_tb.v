`timescale 1ns/1ps
// pcie_status_tb.v —— status 字自校验（DONE/ERR/clear）
module pcie_status_tb;
    reg clk = 0, rst_n = 0;
    reg done_set = 0, err_set = 0, clear = 0;
    reg [2:0] err_code = 0;
    wire [31:0] status;

    pcie_status dut (.clk(clk), .rst_n(rst_n), .done_set(done_set),
                     .err_set(err_set), .err_code(err_code), .clear(clear),
                     .status(status));

    always #5 clk = ~clk;

    integer errors = 0;

    task pulse_done;
        begin @(negedge clk); done_set = 1'b1; @(negedge clk); done_set = 1'b0; end
    endtask
    task pulse_clear;
        begin @(negedge clk); clear = 1'b1; @(negedge clk); clear = 1'b0; end
    endtask
    task pulse_err(input integer c);
        begin
            @(negedge clk); err_set = 1'b1; err_code = c[2:0];
            @(negedge clk); err_set = 1'b0; err_code = 0;
        end
    endtask

    initial begin
        #20 rst_n = 1'b1; #10;

        // done
        pulse_done; #1;
        if (status !== 32'h1) begin errors = errors + 1; $display("FAIL done: %0h", status); end

        // clear
        pulse_clear; #1;
        if (status !== 0) begin errors = errors + 1; $display("FAIL clear: %0h", status); end

        // err code 1
        pulse_err(1); #1;
        if (status[0] !== 1'b1 || status[3:1] !== 3'd1) begin
            errors = errors + 1; $display("FAIL err1: %0h", status);
        end
        pulse_clear;

        // err code 3
        pulse_err(3); #1;
        if (status[0] !== 1'b1 || status[3:1] !== 3'd3) begin
            errors = errors + 1; $display("FAIL err3: %0h", status);
        end
        pulse_clear;

        // clear 后应为 0
        if (status !== 0) begin errors = errors + 1; $display("FAIL final clear: %0h", status); end

        if (errors == 0) $display("pcie_status: ALL checks PASSED");
        else $display("pcie_status: %0d ERRORS", errors);
        $finish;
    end
endmodule

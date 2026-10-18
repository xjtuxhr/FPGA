`timescale 1ns/1ps
module kv_app_status_tb;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, wr_pulse = 0;
    reg [7:0] wr_addr = 0, rd_addr = 8'hA4;
    reg [31:0] wr_data = 0;
    reg [3:0] wr_strb = 0;
    wire [31:0] rd_data;
    reg ddr_ready = 0, bridge_ready = 0, endpoint_idle = 1;
    reg engine_busy = 0, endpoint_fault = 0;
    reg [3:0] endpoint_error = 0;
    reg h2c_accepted = 0, response_accepted = 0;
    wire soft_reset_active;
    integer errors = 0;
    kv_app_status #(.RESET_CYCLES(8'd4)) dut (
        .clk(clk), .rst_n(rst_n), .wr_pulse(wr_pulse), .wr_addr(wr_addr),
        .wr_data(wr_data), .wr_strb(wr_strb), .rd_addr(rd_addr),
        .rd_data(rd_data), .ddr_ready(ddr_ready), .bridge_ready(bridge_ready),
        .endpoint_idle(endpoint_idle), .engine_busy(engine_busy),
        .endpoint_fault(endpoint_fault), .endpoint_error(endpoint_error),
        .h2c_accepted(h2c_accepted), .response_accepted(response_accepted),
        .soft_reset_active(soft_reset_active));
    task step; begin @(posedge clk); #1; end endtask
    task check;
        input [31:0] expected;
        begin
            #1;
            if (rd_data !== expected) begin
                $display("FAIL STATUS got=%h expected=%h", rd_data, expected);
                errors = errors + 1;
            end
        end
    endtask
    task command;
        input [31:0] data;
        input [3:0] strb;
        begin
            @(negedge clk);
            wr_addr = 8'hA8; wr_data = data; wr_strb = strb; wr_pulse = 1;
            step();
            @(negedge clk); wr_pulse = 0;
        end
    endtask
    initial begin
        step(); rst_n = 1;
        check(32'h0);
        ddr_ready = 1; bridge_ready = 1; step();
        check(32'h10); // READY
        response_accepted = 1; step(); response_accepted = 0;
        check(32'h11); // DONE sticks until next H2C
        h2c_accepted = 1; step(); h2c_accepted = 0;
        check(32'h10);
        engine_busy = 1; endpoint_idle = 0;
        step(); check(32'h40); // BUSY and not READY
        command(32'd1, 4'hF);
        check(32'h6E); // rejected reset: BUSY/FAULT/ERR7
        if (soft_reset_active) begin $display("FAIL reset interrupted AXI"); errors=errors+1; end
        engine_busy = 0; endpoint_idle = 1;
        command(32'd1, 4'hF);
        check(32'h40); // resetting: BUSY only
        repeat (6) step();
        check(32'h10);
        endpoint_fault = 1; endpoint_error = 4'd3; step(); endpoint_fault = 0;
        check(32'h26); // FAULT/ERR3
        command(32'd1, 4'hF); repeat (6) step();
        check(32'h10);
        command(32'd3, 4'hF); check(32'h2E); // bad control write
        command(32'd1, 4'hF); repeat (6) step();
        command(32'd2, 4'hF); repeat (6) step();
        check(32'h2E); // abort leaves FAULT until reset
        command(32'd1, 4'hF); repeat (6) step();
        check(32'h10);
        ddr_ready = 0; step();
        check(32'h2E); // DDR loss after ready is sticky
        rd_addr = 8'hA8; #1;
        if (rd_data !== 0) begin $display("FAIL CONTROL readback"); errors=errors+1; end
        if (errors == 0) $display("kv_app_status: ALL checks PASSED");
        else $display("kv_app_status: %0d checks FAILED", errors);
        $finish;
    end
endmodule

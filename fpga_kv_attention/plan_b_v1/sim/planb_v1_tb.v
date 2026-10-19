`timescale 1ns/1ps
module planb_v1_tb;
    reg clk=0;
    always #4 clk=~clk;
    reg rst_n=0, awvalid=0, wvalid=0, arvalid=0;
    reg [31:0] awaddr=0, wdata=0, araddr=0;
    reg start_i=0, done_i=0, engine_fault=0, axi_safe=1, bridge_ready=1;
    reg [2:0] err_i=0;
    wire [31:0] rdata, status;
    wire rsel, soft_req, abort_req, reset_active, block_new, mask_fault;
    wire [31:0] host_rdata = rsel ? rdata : 32'hDEAD_BEEF;
    integer soft_pulses=0, abort_pulses=0, reset_cycles=0;
    planb_status_ctrl u_status (
        .clk(clk), .rst_n(rst_n), .axil_awaddr(awaddr),
        .axil_awvalid(awvalid), .axil_wvalid(wvalid), .axil_wdata(wdata),
        .axil_araddr(araddr), .axil_arvalid(arvalid),
        .start_i(start_i), .done_i(done_i), .ready_i(!block_new),
        .busy_i(block_new), .fault_i(engine_fault && !mask_fault),
        .err_i(err_i), .rdata_o(rdata), .rsel_o(rsel),
        .soft_reset_o(soft_req), .session_abort_o(abort_req),
        .status_o(status));
    planb_reset_guard #(.RESET_CYCLES(8'd8)) u_guard (
        .clk(clk), .rst_n(rst_n), .soft_reset_req(soft_req),
        .session_abort_req(abort_req), .axi_quiescent(axi_safe),
        .bridge_ready(bridge_ready), .reset_active(reset_active),
        .block_new(block_new), .mask_endpoint_fault(mask_fault));
    always @(posedge clk) if (rst_n) begin
        if (soft_req) soft_pulses <= soft_pulses+1;
        if (abort_req) abort_pulses <= abort_pulses+1;
        if (reset_active) reset_cycles <= reset_cycles+1;
    end
    task check;
        input [31:0] got, want;
        begin
            if (got !== want) $fatal(1,"got %08h want %08h",got,want);
        end
    endtask
    task read_reg;
        input [31:0] addr;
        input [31:0] want;
        begin
            @(negedge clk); araddr=addr; arvalid=1;
            @(posedge clk); #1; check(host_rdata,want);
            @(negedge clk); arvalid=0;
        end
    endtask
    task write_cmd;
        input [31:0] addr, value;
        begin
            @(negedge clk); awaddr=addr; wdata=value; awvalid=1; wvalid=1;
            repeat(3) @(posedge clk); // vendor valid remains high for 2 cycles
            @(negedge clk); awvalid=0; wvalid=0;
        end
    endtask
    initial begin
        repeat(3) @(negedge clk); rst_n=1;
        read_reg(32'h0000_00AC,32'h504C_4231);
        read_reg(32'h0008_00AC,32'h504C_4231);
        read_reg(32'h0000_00A8,32'd0); // overrides vendor RAM echo
        check(status,32'h10);
        axi_safe=0;
        write_cmd(32'h0000_00A8,32'd2);
        repeat(3) @(negedge clk);
        check(status,32'h6C); // BUSY + FAULT + ERR=6
        if (abort_pulses != 1 || reset_active) $fatal(1,"abort pulse/quiesce");
        @(negedge clk); start_i=1;
        @(negedge clk); start_i=0;
        check(status,32'h6C); // a rogue START must not clear sticky ERR
        axi_safe=1;
        repeat(18) @(negedge clk);
        if (reset_cycles != 8) $fatal(1,"abort reset stretch=%0d",reset_cycles);
        check(status,32'h2C); // ABORTED remains until SOFT_RESET
        read_reg(32'h0000_00A8,32'd0);
        axi_safe=0; engine_fault=1; err_i=3'd4;
        write_cmd(32'h0008_00A8,32'd1);
        repeat(3) @(negedge clk);
        if (soft_pulses != 1 || reset_active) $fatal(1,"reset before AXI quiescent");
        if (status[4] !== 0 || status[5] !== 0) $fatal(1,"reset pending status %08h",status);
        axi_safe=1;
        repeat(5) @(negedge clk); engine_fault=0; err_i=0;
        repeat(18) @(negedge clk);
        if (reset_cycles != 16) $fatal(1,"soft reset stretch=%0d",reset_cycles);
        check(status,32'h10);
        @(negedge clk); done_i=1;
        @(negedge clk); done_i=0;
        check(status,32'h11);
        @(negedge clk); start_i=1;
        @(negedge clk); start_i=0;
        check(status,32'h10);
        $display("planb_v1: ALL checks PASSED");
        $finish;
    end
    initial begin #100000; $fatal(1,"watchdog"); end
endmodule

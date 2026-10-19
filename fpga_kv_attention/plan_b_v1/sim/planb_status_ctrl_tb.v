// ============================================================================
// planb_status_ctrl_tb.v - self-checking testbench for planb_status_ctrl
//
// Run with any Verilog-2001 simulator, for example:
//   iverilog -o planb_tb planb_status_ctrl_tb.v planb_status_ctrl.v
//   vvp planb_tb
// ============================================================================

`timescale 1ns/1ps

module planb_status_ctrl_tb;

    reg         clk;
    reg         rst_n;

    reg  [31:0] awaddr;
    reg         awvalid;
    reg         wvalid;
    reg  [31:0] wdata;
    reg  [31:0] araddr;
    reg         arvalid;

    reg         start_i;
    reg         done_i;
    reg         ready_i;
    reg         busy_i;
    reg         fault_i;
    reg  [2:0]  err_i;

    wire [31:0] rdata_o;
    wire        rsel_o;
    wire        soft_reset_o;
    wire        session_abort_o;
    wire [31:0] status_o;

    integer errors;

    planb_status_ctrl #(
        .VERSION (32'h504C_4231)
    ) dut (
        .clk             (clk),
        .rst_n           (rst_n),
        .axil_awaddr     (awaddr),
        .axil_awvalid    (awvalid),
        .axil_wvalid     (wvalid),
        .axil_wdata      (wdata),
        .axil_araddr     (araddr),
        .axil_arvalid    (arvalid),
        .start_i         (start_i),
        .done_i          (done_i),
        .ready_i         (ready_i),
        .busy_i          (busy_i),
        .fault_i         (fault_i),
        .err_i           (err_i),
        .rdata_o         (rdata_o),
        .rsel_o          (rsel_o),
        .soft_reset_o    (soft_reset_o),
        .session_abort_o (session_abort_o),
        .status_o        (status_o)
    );

    always #4 clk = ~clk;

    task axil_write;
        input [31:0] addr;
        input [31:0] data;
        begin
            @(posedge clk);
            awaddr  = addr;
            wdata   = data;
            awvalid = 1'b1;
            wvalid  = 1'b1;
            @(posedge clk);
            awvalid = 1'b0;
            wvalid  = 1'b0;
            @(posedge clk);
        end
    endtask

    task axil_read;
        input  [31:0] addr;
        output [31:0] data;
        begin
            @(posedge clk);
            araddr  = addr;
            arvalid = 1'b1;
            @(posedge clk);
            arvalid = 1'b0;
            #1 data = rdata_o;
            @(posedge clk);
        end
    endtask

    task check;
        input [31:0] got;
        input [31:0] exp;
        input [127:0] name;
        begin
            if (got !== exp) begin
                $display("FAIL %0s: got 0x%08x expected 0x%08x",
                         name, got, exp);
                errors = errors + 1;
            end else begin
                $display("PASS %0s: 0x%08x", name, got);
            end
        end
    endtask

    reg [31:0] rd;

    initial begin
        clk     = 1'b0;
        rst_n   = 1'b0;
        awaddr  = 32'd0;
        awvalid = 1'b0;
        wvalid  = 1'b0;
        wdata   = 32'd0;
        araddr  = 32'd0;
        arvalid = 1'b0;
        start_i = 1'b0;
        done_i  = 1'b0;
        ready_i = 1'b1;
        busy_i  = 1'b0;
        fault_i = 1'b0;
        err_i   = 3'd0;
        errors  = 0;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        // VERSION and initial STATUS
        axil_read(32'h0000_00AC, rd);
        check(rd, 32'h504C_4231, "VERSION");
        axil_read(32'h0000_00A4, rd);
        check(rd, 32'h0000_0010, "STATUS initial READY");

        // CONTROL reads as zero even though the write aliases SGDMA RAM
        axil_write(32'h0000_00A8, 32'h0000_0000);
        axil_read(32'h0000_00A8, rd);
        check(rd, 32'h0000_0000, "CONTROL reads zero");

        // SESSION_ABORT -> FAULT + ERR=6, not READY/DONE
        axil_write(32'h0000_00A8, 32'h0000_0002);
        @(posedge clk);
        axil_read(32'h0000_00A4, rd);
        check(rd, 32'h0000_002C, "STATUS after SESSION_ABORT");

        // SOFT_RESET -> READY, no FAULT/ERR
        axil_write(32'h0000_00A8, 32'h0000_0001);
        @(posedge clk);
        axil_read(32'h0000_00A4, rd);
        check(rd, 32'h0000_0010, "STATUS after SOFT_RESET");

        // Normal completion: START clears, DONE sets
        @(posedge clk);
        start_i = 1'b1;
        @(posedge clk);
        start_i = 1'b0;
        done_i  = 1'b1;
        err_i   = 3'd0;
        @(posedge clk);
        done_i  = 1'b0;
        axil_read(32'h0000_00A4, rd);
        check(rd, 32'h0000_0011, "STATUS after DONE");

        // Error completion: ERR=1 latches FAULT and forces DONE=0
        @(posedge clk);
        start_i = 1'b1;
        @(posedge clk);
        start_i = 1'b0;
        done_i  = 1'b1;
        err_i   = 3'd1;
        @(posedge clk);
        done_i  = 1'b0;
        axil_read(32'h0000_00A4, rd);
        check(rd, 32'h0000_0022, "STATUS after ERR=1");

        // FAULT without an explicit code maps to INTERNAL=5
        axil_write(32'h0000_00A8, 32'h0000_0001);
        @(posedge clk);
        @(posedge clk);
        fault_i = 1'b1;
        err_i   = 3'd0;
        @(posedge clk);
        fault_i = 1'b0;
        axil_read(32'h0000_00A4, rd);
        check(rd, 32'h0000_002A, "STATUS FAULT->INTERNAL");

        // Final reset leaves the block ready
        axil_write(32'h0000_00A8, 32'h0000_0001);
        @(posedge clk);
        axil_read(32'h0000_00A4, rd);
        check(rd, 32'h0000_0010, "STATUS final reset");

        if (errors == 0)
            $display("ALL PLANB STATUS TESTS PASSED");
        else
            $display("%0d PLANB STATUS TESTS FAILED", errors);

        $finish;
    end

endmodule

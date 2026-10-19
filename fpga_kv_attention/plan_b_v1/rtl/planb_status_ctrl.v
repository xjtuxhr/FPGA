// ============================================================================
// planb_status_ctrl.v - Plan B endpoint STATUS/CONTROL/VERSION registers
//
// BAR0 (user), 32-bit, 4-byte aligned:
//   0xA4  STATUS   read-only
//   0xA8  CONTROL  write-only, self-clearing commands (read returns 0)
//   0xAC  VERSION  read-only, "PLB1"
//
// The top level must select rdata_o when rsel_o is high, with priority over
// the video register block and the SGDMA application read data.  The top level
// must also connect soft_reset_o / session_abort_o to the application logic.
//
// This module does not reset the PCIe HIP, BAR or link.  It only resets the
// application state and reports status.
// ============================================================================

`timescale 1ns/1ps

module planb_status_ctrl #(
    parameter [31:0] VERSION = 32'h504C_4231  // "PLB1"
)(
    input  wire        clk,
    input  wire        rst_n,

    // AXI-Lite master side, BAR0 logical offsets
    input  wire [31:0] axil_awaddr,
    input  wire        axil_awvalid,
    input  wire        axil_wvalid,
    input  wire [31:0] axil_wdata,
    input  wire [31:0] axil_araddr,
    input  wire        axil_arvalid,

    // Application engine status
    input  wire        start_i,
    input  wire        done_i,
    input  wire        ready_i,
    input  wire        busy_i,
    input  wire        fault_i,
    input  wire [2:0]  err_i,

    // AXI-Lite read override
    output wire [31:0] rdata_o,
    output wire        rsel_o,

    // Application control pulses (one user_clk cycle)
    output wire        soft_reset_o,
    output wire        session_abort_o,

    // Debug/status visibility
    output wire [31:0] status_o
);

    localparam [7:0] ADDR_STATUS  = 8'hA4;
    localparam [7:0] ADDR_CONTROL = 8'hA8;
    localparam [7:0] ADDR_VERSION = 8'hAC;

    localparam [2:0] ERR_OK       = 3'd0;
    localparam [2:0] ERR_INTERNAL = 3'd5;
    localparam [2:0] ERR_ABORTED  = 3'd6;

    // ------------------------------------------------------------------------
    // Write command decode.  The rising edge of the hit avoids double pulses
    // when awvalid/wvalid stay high for more than one user_clk.
    // ------------------------------------------------------------------------
    wire wr_hit = axil_awvalid && axil_wvalid &&
                  (axil_awaddr[15:8] == 8'h00) &&
                  (axil_awaddr[7:0] == ADDR_CONTROL);

    reg wr_hit_d1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            wr_hit_d1 <= 1'b0;
        else
            wr_hit_d1 <= wr_hit;
    end

    wire cmd_pulse = wr_hit && !wr_hit_d1;

    reg soft_reset_r;
    reg session_abort_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            soft_reset_r    <= 1'b0;
            session_abort_r <= 1'b0;
        end else begin
            soft_reset_r    <= 1'b0;
            session_abort_r <= 1'b0;

            if (cmd_pulse) begin
                if (axil_wdata[0])
                    soft_reset_r <= 1'b1;
                else if (axil_wdata[1])
                    session_abort_r <= 1'b1;
            end
        end
    end

    assign soft_reset_o    = soft_reset_r;
    assign session_abort_o = session_abort_r;

    // ------------------------------------------------------------------------
    // Status state.  FAULT and ABORTED are sticky until SOFT_RESET.  DONE/ERR
    // are cleared when a new request starts or when SOFT_RESET is written.
    // ------------------------------------------------------------------------
    reg        done_l;
    reg        fault_l;
    reg        abort_l;
    reg [2:0]  err_l;

    wire err_present  = (err_i != ERR_OK);
    wire fatal_event  = fault_i || (done_i && err_present);
    wire [2:0] err_event = (fault_i && !err_present) ? ERR_INTERNAL : err_i;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            done_l  <= 1'b0;
            fault_l <= 1'b0;
            abort_l <= 1'b0;
            err_l   <= ERR_OK;
        end else if (soft_reset_r) begin
            done_l  <= 1'b0;
            fault_l <= 1'b0;
            abort_l <= 1'b0;
            err_l   <= ERR_OK;
        end else begin
            // A stale or malformed start must not clear the recorded error
            // while FAULT is latched. Only SOFT_RESET releases that state.
            if (start_i && !fault_l) begin
                done_l <= 1'b0;
                err_l  <= ERR_OK;
            end

            if (done_i && !fault_l) begin
                done_l <= !fatal_event;
                err_l  <= err_event;
            end

            if (fatal_event && !fault_l) begin
                fault_l <= 1'b1;
                err_l   <= err_event;
            end

            if (session_abort_r) begin
                done_l  <= 1'b0;
                fault_l <= 1'b1;
                abort_l <= 1'b1;
                err_l   <= ERR_ABORTED;
            end
        end
    end

    wire [2:0] err_visible = abort_l ? ERR_ABORTED : err_l;

    assign status_o = {25'd0,
                       busy_i,
                       fault_l,
                       (ready_i && !fault_l && !busy_i && !soft_reset_r),
                       err_visible,
                       (done_l && !fault_l)};

    // ------------------------------------------------------------------------
    // Read override.  Register the select and data to match the existing
    // video-register read path (one user_clk after arvalid/araddr).
    // 0xA8 reads as zero even though writes also alias into the SGDMA RAM.
    // ------------------------------------------------------------------------
    wire rd_hit = axil_arvalid &&
                  (axil_araddr[15:8] == 8'h00) &&
                  ((axil_araddr[7:0] == ADDR_STATUS) ||
                   (axil_araddr[7:0] == ADDR_CONTROL) ||
                   (axil_araddr[7:0] == ADDR_VERSION));

    reg        rsel_r;
    reg [31:0] rdata_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            rsel_r <= 1'b0;
        else
            rsel_r <= rd_hit;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            rdata_r <= 32'd0;
        else begin
            case (axil_araddr[7:0])
                ADDR_STATUS:  rdata_r <= status_o;
                ADDR_CONTROL: rdata_r <= 32'd0;
                ADDR_VERSION: rdata_r <= VERSION;
                default:      rdata_r <= 32'd0;
            endcase
        end
    end

    assign rdata_o = rdata_r;
    assign rsel_o  = rsel_r;

endmodule

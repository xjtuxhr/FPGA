`timescale 1ns/1ps
// Holds an application-only reset until both clock domains have observed it.
// A command is queued while an AXI burst is outstanding; it never truncates
// an accepted DDR transaction. The host must use hardware recovery if the
// AXI master cannot reach a quiescent state (for example after a timeout).
module planb_reset_guard #(
    parameter [7:0] RESET_CYCLES = 8'd16
)(
    input  wire clk,
    input  wire rst_n,
    input  wire soft_reset_req,
    input  wire session_abort_req,
    input  wire axi_quiescent,
    input  wire bridge_ready,
    output wire reset_active,
    output wire block_new,
    output wire mask_endpoint_fault
);
    localparam [1:0] IDLE=2'd0, WAIT_AXI=2'd1,
                     ASSERT_RESET=2'd2, WAIT_RELEASE=2'd3;
    reg [1:0] state;
    reg [7:0] reset_left;
    reg [2:0] quiet_count;

    assign reset_active = (state == ASSERT_RESET);
    assign block_new = (state != IDLE) || soft_reset_req || session_abort_req;
    assign mask_endpoint_fault = (state != IDLE) || soft_reset_req;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            reset_left <= 0;
            quiet_count <= 0;
        end else begin
            if (state != WAIT_AXI || !axi_quiescent) quiet_count <= 0;
            else if (quiet_count != 3'd4) quiet_count <= quiet_count + 1'b1;
            case (state)
                IDLE: begin
                    if (soft_reset_req || session_abort_req)
                        state <= WAIT_AXI;
                end
                WAIT_AXI: begin
                    if (axi_quiescent && quiet_count == 3'd4) begin
                        reset_left <= RESET_CYCLES;
                        state <= ASSERT_RESET;
                    end
                end
                ASSERT_RESET: begin
                    if (reset_left == 8'd1) begin
                        reset_left <= 0;
                        state <= WAIT_RELEASE;
                    end else reset_left <= reset_left - 1'b1;
                end
                WAIT_RELEASE: begin
                    if (bridge_ready && axi_quiescent) state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule

`timescale 1ns/1ps
// Candidate PC2/B BAR0 application registers. All inputs are in usr_clk.
// STATUS @0xA4: DONE[0], ERR[3:1], READY[4], FAULT[5], BUSY[6].
// CONTROL @0xA8: write 1=SOFT_RESET, 2=SESSION_ABORT, full 32-bit writes only.
module kv_app_status #(
    parameter [7:0] RESET_CYCLES = 8'd16
)(
    input wire clk, rst_n,
    input wire wr_pulse,
    input wire [7:0] wr_addr,
    input wire [31:0] wr_data,
    input wire [3:0] wr_strb,
    input wire [7:0] rd_addr,
    output reg [31:0] rd_data,
    input wire ddr_ready,
    input wire bridge_ready,
    input wire endpoint_idle,
    input wire engine_busy,
    input wire endpoint_fault,
    input wire [3:0] endpoint_error,
    input wire h2c_accepted,
    input wire response_accepted,
    output wire soft_reset_active
);
    localparam [7:0] REG_STATUS = 8'hA4, REG_CONTROL = 8'hA8;
    localparam [2:0] ERR_DDR_OR_CONTROL = 3'd7;
    reg [7:0] reset_left;
    reg seen_ddr, sticky_fault, sticky_done;
    reg [2:0] sticky_error;
    wire ctrl_write = wr_pulse && wr_addr == REG_CONTROL;
    wire ctrl_reset = ctrl_write && wr_strb == 4'hF && wr_data == 32'd1;
    wire ctrl_abort = ctrl_write && wr_strb == 4'hF && wr_data == 32'd2;
    wire ctrl_bad = ctrl_write && !ctrl_reset && !ctrl_abort;
    wire busy = !endpoint_idle || engine_busy || soft_reset_active;
    wire ready = ddr_ready && bridge_ready && endpoint_idle &&
                 !engine_busy && !sticky_fault && !endpoint_fault &&
                 !soft_reset_active;
    assign soft_reset_active = reset_left != 0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reset_left <= 0;
            seen_ddr <= 0;
            sticky_fault <= 0;
            sticky_done <= 0;
            sticky_error <= 0;
        end else begin
            if (reset_left != 0) reset_left <= reset_left - 1'b1;
            if (ddr_ready) seen_ddr <= 1'b1;
            if (h2c_accepted) sticky_done <= 1'b0;
            if (response_accepted && !soft_reset_active) sticky_done <= 1'b1;
            if (!soft_reset_active) begin
                if (seen_ddr && !ddr_ready) begin
                    sticky_fault <= 1'b1;
                    sticky_error <= ERR_DDR_OR_CONTROL;
                end else if (endpoint_fault && !sticky_fault) begin
                    sticky_fault <= 1'b1;
                    sticky_error <= endpoint_error[3] ? 3'd7 : endpoint_error[2:0];
                end
            end
            if (ctrl_write && !soft_reset_active) begin
                // Do not reset a DDR AXI master with an outstanding burst.
                if (engine_busy || ctrl_bad) begin
                    sticky_fault <= 1'b1;
                    sticky_error <= ERR_DDR_OR_CONTROL;
                end else if (ctrl_reset) begin
                    reset_left <= RESET_CYCLES;
                    seen_ddr <= 1'b0;
                    sticky_fault <= 1'b0;
                    sticky_done <= 1'b0;
                    sticky_error <= 0;
                end else if (ctrl_abort) begin
                    // Candidate semantics: discard queued app frames and KV
                    // history, then require an explicit SOFT_RESET to rearm.
                    reset_left <= RESET_CYCLES;
                    seen_ddr <= 1'b0;
                    sticky_fault <= 1'b1;
                    sticky_done <= 1'b0;
                    sticky_error <= ERR_DDR_OR_CONTROL;
                end
            end
        end
    end

    // The top-level vendor BAR mux registers this value on a read request.
    always @(*) begin
        case (rd_addr)
            REG_STATUS: rd_data = {25'd0, busy, sticky_fault,
                                   ready, sticky_error, sticky_done};
            REG_CONTROL: rd_data = 32'd0;
            default: rd_data = 32'd0;
        endcase
    end
endmodule

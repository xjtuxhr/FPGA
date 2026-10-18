`timescale 1ns/1ps
// Bundled-data mailbox: source holds the complete snapshot until acknowledged.
// Reset either side cancels the mailbox. Data bus must retain physical CDC
// settling constraints in board P&R; functional simulation is not CDC signoff.
module diag_snapshot_cdc #(parameter WIDTH=40)(
    input wire src_clk, src_rst_n,
    input wire [WIDTH-1:0] src_data,
    input wire dst_clk, dst_rst_n,
    output reg [WIDTH-1:0] dst_data
);
    wire reset_n=src_rst_n && dst_rst_n;
    reg [WIDTH-1:0] hold_data;
    reg request, acknowledge;
    (* ASYNC_REG="TRUE" *) reg [1:0] ack_sync, req_sync;
    always @(posedge src_clk or negedge reset_n) begin
        if(!reset_n) begin hold_data<=0; request<=0; ack_sync<=0; end
        else begin
            ack_sync<={ack_sync[0],acknowledge};
            if(request==ack_sync[1] && hold_data!=src_data) begin
                hold_data<=src_data; request<=!request;
            end
        end
    end
    always @(posedge dst_clk or negedge reset_n) begin
        if(!reset_n) begin dst_data<=0; acknowledge<=0; req_sync<=0; end
        else begin
            req_sync<={req_sync[0],request};
            if(req_sync[1]!=acknowledge) begin dst_data<=hold_data; acknowledge<=req_sync[1]; end
        end
    end
endmodule

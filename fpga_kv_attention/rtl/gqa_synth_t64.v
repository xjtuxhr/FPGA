`timescale 1ns/1ps
// gqa_synth_t64.v —— GQA attention 真实尺寸综合顶层（T=64），仅资源/时序评估用
module gqa_synth_t64 (
    input  wire clk,
    input  wire rst_n,
    output wire [31:0] status
);
    reg [15:0] stim;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) stim <= 16'd0;
        else        stim <= stim + 16'd1;
    end
    wire signed [15:0] s16 = $signed(stim);
    wire out_valid;
    wire signed [31:0] out;
    wire [7:0] out_head, out_d;

    gqa_attention #(.H(9), .G(3), .D(64), .T(64), .DATA_W(16)) u_gqa (
        .clk(clk), .rst_n(rst_n), .start(stim[0]),
        .q_valid(stim[1]), .q_in(s16),
        .k_valid(stim[2]), .k_in(s16),
        .v_valid(stim[3]), .v_in(s16),
        .out_valid(out_valid), .out(out), .out_head(out_head), .out_d(out_d));

    assign status = out ^ {16'd0, out_head, out_d} ^ {31'd0, out_valid};
endmodule

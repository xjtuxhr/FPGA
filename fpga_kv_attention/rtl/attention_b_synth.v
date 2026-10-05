`timescale 1ns/1ps
// attention_b_synth.v —— Attention-only B 通路综合顶层（真实尺寸 H=9/G=3/D=64/T=64）
// 仅资源/时序评估用，不上板。
module attention_b_synth (
    input  wire clk,
    input  wire rst_n,
    output wire [31:0] status
);
    reg [15:0] stim;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) stim <= 16'd0;
        else        stim <= stim + 16'd1;
    end
    wire out_valid;
    wire signed [31:0] out;
    wire [7:0] out_head, out_d;

    attention_b_top #(.H(9), .G(3), .D(64), .T(64)) u_b (
        .clk(clk), .rst_n(rst_n), .start(stim[0]),
        .q_valid(stim[1]), .q_fp16(stim),
        .k_valid(stim[2]), .k_fp16(stim),
        .v_valid(stim[3]), .v_fp16(stim),
        .out_valid(out_valid), .out(out), .out_head(out_head), .out_d(out_d));

    assign status = out ^ {16'd0, out_head, out_d} ^ {31'd0, out_valid};
endmodule

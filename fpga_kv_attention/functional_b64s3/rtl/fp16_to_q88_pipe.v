`timescale 1ns/1ps
// Three-stage FP16->Q8.8, exact fp16_to_q88 semantics with a one-bit tag.
// Bounded 12/16-bit shifts replace the large 27-bit rounding barrel.
module fp16_to_q88_pipe(
 input wire clk,rst_n,in_valid,in_tag,
 input wire [15:0] fp16,
 output reg out_valid,out_tag,
 output reg signed [15:0] q88
);
 reg v1,t1,s1,v2,t2,s2;
 reg [4:0] e1;
 reg [10:0] sig1;
 reg [15:0] mag2;
 wire [11:0] rounded_sig = {1'b0,sig1} + (12'd1 << (5'd16-e1));
 always @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
     v1<=0;t1<=0;s1<=0;e1<=0;sig1<=0;
     v2<=0;t2<=0;s2<=0;mag2<=0;
     out_valid<=0;out_tag<=0;q88<=0;
   end else begin
     v1<=in_valid;t1<=in_tag;s1<=fp16[15];e1<=fp16[14:10];sig1<={1'b1,fp16[9:0]};
     v2<=v1;t2<=t1;s2<=s1;
     if(e1<=5) mag2<=0;
     else if(e1>=22) mag2<=32767;
     else if(e1>=17) mag2<={5'd0,sig1} << (e1-17);
     else mag2<=rounded_sig >> (17-e1);
     out_valid<=v2;out_tag<=t2;
     q88<=s2 ? -$signed(mag2) : $signed(mag2);
   end
 end
endmodule

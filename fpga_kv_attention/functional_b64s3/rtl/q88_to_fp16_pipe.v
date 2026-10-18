`timescale 1ns/1ps
// Three registered conversion stages. Matches q88_to_fp16 round-half-away.
// No backpressure: one word/cycle; LAST travels with VALID and the data.
module q88_to_fp16_pipe(
 input wire clk, rst_n, in_valid, in_last,
 input wire signed [15:0] q88,
 output reg out_valid, out_last,
 output reg [15:0] fp16
);
 wire [15:0] mag = q88[15] ? (~q88+16'd1) : q88;
 reg [3:0] high_bit;
 integer i;
 always @(*) begin
   high_bit=0;
   for(i=0;i<16;i=i+1) if(mag[i]) high_bit=i;
 end
 reg v1,l1,s1,z1,v2,l2,s2,z2;
 reg [15:0] m1, sig2;
 reg [3:0] h1;
 reg [4:0] e2;
 always @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
     v1<=0; l1<=0; s1<=0; z1<=1; m1<=0; h1<=0;
     v2<=0; l2<=0; s2<=0; z2<=1; sig2<=0; e2<=0;
     out_valid<=0; out_last<=0; fp16<=0;
   end else begin
     v1<=in_valid; l1<=in_last; s1<=q88[15]; z1<=mag==0; m1<=mag; h1<=high_bit;
     v2<=v1; l2<=l1; s2<=s1; z2<=z1; e2<=5'd7+h1;
     if(h1>10) sig2<=(m1+(16'd1<<(h1-11)))>>(h1-10);
     else sig2<=m1<<(10-h1);
     out_valid<=v2; out_last<=l2;
     if(z2) fp16<={s2,15'd0};
     else if(sig2==2048) fp16<={s2,(e2+5'd1),10'd0};
     else fp16<={s2,e2,sig2[9:0]};
   end
 end
endmodule

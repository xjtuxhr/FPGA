`timescale 1ns/1ps
// ============================================================================
// kv_quant_demo.v —— 顶层演示（无复位版，适配 MLK-AFH03-AFC03）
//
// 只有时钟 + 输出，不需要复位按键：
//   25MHz 时钟（T16）驱动计数器 → kv_quant 量化 → 结果输出到 FMC LA 引脚。
//   上电后寄存器默认为 0，计数器从 0 开始循环，无需外部复位。
//
// 引脚（按手册）：
//   clk       -> FPGA_SYSCLK_25MHZ @ T16
//   gpio[3:0] -> FMC_HPC_LA00_CC_P / LA03_P / LA08_P / LA12_P
// ============================================================================
module kv_quant_demo (
    input  wire clk,          // 25MHz @ T16
    output wire [3:0] gpio    // 量化结果 q，输出到 FMC LA 引脚
);

    localparam CLK_FREQ = 25_000_000;   // 25MHz
    localparam STEP     = CLK_FREQ / 2; // 0.5s 一步
    localparam CNT_W    = 24;           // 2^24 > 12.5M

    reg [CNT_W-1:0] cnt     = {CNT_W{1'b0}};  // 上电默认 0
    reg [3:0]       counter = 4'd0;            // 0..15 慢计数器

    always @(posedge clk) begin
        if (cnt >= STEP - 1) begin
            cnt     <= {CNT_W{1'b0}};
            counter <= counter + 1'b1;   // 0.5s 加 1，4-bit 自然回绕 0..15
        end else begin
            cnt <= cnt + 1'b1;
        end
    end

    // x = counter << 8（Q8.8），min=0，inv_scale=256（值 1.0）-> q = counter
    wire signed [15:0] x         = {4'b0, counter, 8'b0};
    wire signed [15:0] min       = 16'sd0;
    wire        [15:0] inv_scale = 16'd256;

    wire [3:0] q;
    kv_quant #(.Q_BITS(4), .X_W(16), .INV_W(16))
        u_quant (
            .clk(clk), .rst_n(1'b1), .valid_in(1'b1),
            .x(x), .min(min), .inv_scale(inv_scale),
            .valid_out(), .q(q)
        );

    assign gpio = q;   // q 输出到 FMC LA 引脚

endmodule

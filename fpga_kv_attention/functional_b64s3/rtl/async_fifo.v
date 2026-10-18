`timescale 1ns/1ps
// ============================================================================
// async_fifo.v —— 双时钟异步 FIFO（AXI-Stream 跨时钟域）
//
// 格雷码指针 + 2 级同步，标准 Cummings 结构。写侧 w_valid/w_ready，读侧
// r_valid/r_ready，数据打包透传（tdata+tlast+tkeep 等由上层决定宽度）。
// 深度须为 2 的幂。首字回退（fall-through）。
// ============================================================================
module async_fifo #(
    parameter DATA_W = 145,    // 数据位宽（tdata+tlast+tkeep 打包）
    parameter DEPTH  = 256,    // 深度（2 的幂）
    parameter ADDR_W = 8       // log2(DEPTH)
)(
    input  wire w_clk,
    input  wire w_rst_n,
    input  wire w_valid,
    input  wire [DATA_W-1:0] w_data,
    output wire w_ready,

    input  wire r_clk,
    input  wire r_rst_n,
    output wire r_valid,
    output wire [DATA_W-1:0] r_data,
    input  wire r_ready
);
    reg [DATA_W-1:0] mem [0:DEPTH-1];

    // 二进制指针（用于寻址）+ 格雷码指针（用于 CDC）
    reg [ADDR_W:0] wbin, rbin;
    reg [ADDR_W:0] wgray, rgray;
    // 跨域同步后的格雷码指针（2 级同步）
    (* ASYNC_REG = "TRUE" *) reg [ADDR_W:0] wgray_sync1_r, wgray_sync2_r;   // 写指针同步到读域
    (* ASYNC_REG = "TRUE" *) reg [ADDR_W:0] rgray_sync1_w, rgray_sync2_w;   // 读指针同步到写域

    // bin -> gray
    wire [ADDR_W:0] wbin_next = wbin + 1'b1;
    wire [ADDR_W:0] rbin_next = rbin + 1'b1;
    wire [ADDR_W:0] wgray_next = (wbin_next >> 1) ^ wbin_next;
    wire [ADDR_W:0] rgray_next = (rbin_next >> 1) ^ rbin_next;

    // full（写侧）：wgray 与 rgray_sync2_w 的高两位相反、其余相同
    wire w_full = (wgray[ADDR_W]   != rgray_sync2_w[ADDR_W]) &&
                  (wgray[ADDR_W-1] != rgray_sync2_w[ADDR_W-1]) &&
                  (wgray[ADDR_W-2:0] == rgray_sync2_w[ADDR_W-2:0]);
    // empty（读侧）：wgray_sync2_r == rgray
    wire r_empty = (wgray_sync2_r == rgray);

    assign w_ready = w_rst_n && ~w_full;
    assign r_valid = r_rst_n && ~r_empty;
    assign r_data  = mem[rbin[ADDR_W-1:0]];

    // ---- 写侧 ----
    always @(posedge w_clk or negedge w_rst_n) begin
        if (!w_rst_n) begin
            wbin <= 0; wgray <= 0;
            rgray_sync1_w <= 0; rgray_sync2_w <= 0;
        end else begin
            // 读指针 2 级同步到写域
            rgray_sync1_w <= rgray;
            rgray_sync2_w <= rgray_sync1_w;
            if (w_valid && ~w_full) begin
                mem[wbin[ADDR_W-1:0]] <= w_data;
                wbin  <= wbin_next;
                wgray <= wgray_next;
            end
        end
    end

    // ---- 读侧 ----
    always @(posedge r_clk or negedge r_rst_n) begin
        if (!r_rst_n) begin
            rbin <= 0; rgray <= 0;
            wgray_sync1_r <= 0; wgray_sync2_r <= 0;
        end else begin
            // 写指针 2 级同步到读域
            wgray_sync1_r <= wgray;
            wgray_sync2_r <= wgray_sync1_r;
            if (r_valid && r_ready) begin
                rbin  <= rbin_next;
                rgray <= rgray_next;
            end
        end
    end

endmodule

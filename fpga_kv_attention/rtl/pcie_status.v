`timescale 1ns/1ps
// ============================================================================
// pcie_status.v —— PCIe status 字（spec v0.2）：[0]DONE / [3:1]ERR / [31:4]reserved
//
// transport 用 4B control pread 读。本模块是纯寄存器，暴露 status[31:0]。
// done_set 置 DONE；err_set 置 ERR（并同时置 DONE，表示"本层已结束但有错"）；
// clear 清空（新请求）。
// ============================================================================
module pcie_status (
    input  wire clk,
    input  wire rst_n,
    input  wire done_set,       // 脉冲：本层完成
    input  wire err_set,        // 脉冲：出错
    input  wire [2:0] err_code, // 1=SEQ_ERR 2=LAYER_ERR 3=CRC_ERR
    input  wire clear,          // 脉冲：清空（新请求）
    output reg  [31:0] status
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            status <= 32'd0;
        end else begin
            if (clear) begin
                status <= 32'd0;
            end else begin
                if (done_set) status[0] <= 1'b1;
                if (err_set) begin
                    status[0]   <= 1'b1;    // 错误也算本层结束
                    status[3:1] <= err_code;
                end
            end
        end
    end

endmodule

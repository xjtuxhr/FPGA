`timescale 1ns/1ps
// ============================================================================
// min_max_reduce.v —— 分组求 min/max（KVmix 量化的第一步）
//
// 输入：一组数据流（组内逐元素进入，valid_in=1 表示有效）
// 输出：每个组结束给出 min_out/max_out（含组内最后一个元素）
//
// 用途：K 按通道沿 token 轴分组、V 按 token 沿通道轴分组，每组求 min/max
//       之后由上游/软件算 inv_scale = qmax/(max-min)，交给 kv_quant。
// ============================================================================
module min_max_reduce #(
    parameter DATA_W     = 16,    // 数据位宽（Q8.8 有符号）
    parameter GROUP_SIZE = 32     // 组大小
)(
    input  wire clk,
    input  wire rst_n,
    input  wire valid_in,
    input  wire signed [DATA_W-1:0] value,
    output reg  group_done,                       // 组结束脉冲
    output reg  signed [DATA_W-1:0] min_out,
    output reg  signed [DATA_W-1:0] max_out
);
    // 用固定位宽，避免 $clog2 的兼容性问题（支持 GROUP_SIZE <= 64）
    localparam CNT_W = 6;

    reg [CNT_W-1:0] cnt;
    reg signed [DATA_W-1:0] min_r, max_r;

    // 组合逻辑：把当前元素并入 min/max
    wire signed [DATA_W-1:0] next_min =
        (cnt == 0) ? value : ((value < min_r) ? value : min_r);
    wire signed [DATA_W-1:0] next_max =
        (cnt == 0) ? value : ((value > max_r) ? value : max_r);
    wire is_last = (cnt == GROUP_SIZE-1);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt        <= {CNT_W{1'b0}};
            min_r      <= {DATA_W{1'b0}};
            max_r      <= {DATA_W{1'b0}};
            group_done <= 1'b0;
            min_out    <= {DATA_W{1'b0}};
            max_out    <= {DATA_W{1'b0}};
        end else begin
            group_done <= 1'b0;
            if (valid_in) begin
                min_r <= next_min;
                max_r <= next_max;
                if (is_last) begin
                    min_out    <= next_min;   // 含最后一个元素
                    max_out    <= next_max;
                    group_done <= 1'b1;
                    cnt        <= {CNT_W{1'b0}};
                end else begin
                    cnt <= cnt + 1'b1;
                end
            end
        end
    end

endmodule

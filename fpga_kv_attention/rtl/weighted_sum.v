`timescale 1ns/1ps
// ============================================================================
// weighted_sum.v —— 加权求和（attention 的 PV 输出计算）
//
//   out[d] = sum_{t=0}^{T-1} p[t] * v[t][d]      (d = 0..D-1)
//
// 用途：PV —— p = softmax 概率，v = value，out = attention 输出向量。
// 定点格式（CANDIDATE）：p 为 Q0.16 无符号，v 为 Q8.8 有符号，out 为 32-bit。
//
// 接口（按 token 顺序输入）：
//   start 复位累加器；然后对每个 token t：
//     先 p_valid + p（1 拍），再 v_valid + v 连续 D 拍（v_t[0..D-1]）。
//   T 个 token 全部累加完后，out_valid + out + out_idx 连续 D 拍输出结果。
// ============================================================================
module weighted_sum #(
    parameter T     = 256,    // token 数（context 长度）
    parameter D     = 64,     // head_dim
    parameter P_W   = 16,     // 概率位宽（Q0.16）
    parameter V_W   = 16      // 值位宽（Q8.8）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire start,             // 复位累加器，开始新一组
    input  wire p_valid,           // 新 token 的概率到达
    input  wire [P_W-1:0] p,
    input  wire v_valid,           // 值元素到达
    input  wire signed [V_W-1:0] v,
    output reg  out_valid,
    output reg  signed [31:0] out,
    output reg  [6:0] out_idx      // 0..D-1
);
    reg signed [31:0] acc [0:D-1]; // D 个累加器
    reg [P_W-1:0] p_r;
    reg [7:0] t_cnt;
    reg [6:0] d_cnt;
    reg [6:0] emit_cnt;
    reg [1:0] state;

    localparam S_IDLE = 2'd0, S_ACC = 2'd1, S_EMIT = 2'd2;

    integer i;
    initial begin
        for (i = 0; i < D; i = i + 1) acc[i] = 32'sd0;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_IDLE;
            p_r      <= {P_W{1'b0}};
            t_cnt    <= 8'd0;
            d_cnt    <= 7'd0;
            emit_cnt <= 7'd0;
            out_valid<= 1'b0;
            out      <= 32'sd0;
            out_idx  <= 7'd0;
        end else begin
            out_valid <= 1'b0;
            case (state)
                S_IDLE: begin
                    if (start) begin
                        for (i = 0; i < D; i = i + 1) acc[i] <= 32'sd0;
                        t_cnt <= 8'd0;
                        d_cnt <= 7'd0;
                        state <= S_IDLE;
                    end
                    if (p_valid) begin
                        p_r   <= p;
                        d_cnt <= 7'd0;
                        state <= S_ACC;
                    end
                end
                S_ACC: begin
                    if (v_valid) begin
                        acc[d_cnt] <= acc[d_cnt] + ($signed({1'b0, p_r}) * $signed(v));
                        if (d_cnt == D - 1) begin
                            d_cnt <= 7'd0;
                            if (t_cnt == T - 1) begin
                                emit_cnt <= 7'd0;
                                state    <= S_EMIT;
                            end else begin
                                t_cnt <= t_cnt + 1'b1;
                                state <= S_IDLE;   // 等下一个 token 的 p
                            end
                        end else begin
                            d_cnt <= d_cnt + 1'b1;
                        end
                    end
                end
                S_EMIT: begin
                    out       <= acc[emit_cnt];
                    out_idx   <= emit_cnt;
                    out_valid <= 1'b1;
                    if (emit_cnt == D - 1) begin
                        state <= S_IDLE;
                    end else begin
                        emit_cnt <= emit_cnt + 1'b1;
                    end
                end
            endcase
        end
    end

endmodule

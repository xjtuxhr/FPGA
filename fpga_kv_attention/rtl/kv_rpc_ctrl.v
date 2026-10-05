`timescale 1ns/1ps
// ============================================================================
// kv_rpc_ctrl.v —— RPC (Recent Pivotal Context) tail 管理控制状态机（M 方案）
//
// 维护 KV cache 的环形窗口与 recent FP16 tail 边界。CANDIDATE：T=256、M=32
// （KV-001 候选默认，未冻结；要求 T 为 2 的幂、M < T）。
//
// 行为：
//   - 每个 new_token：该 token 的 KV 以 FP16 写入 slot=head(=token_id mod T)。
//   - 当 token_id >= M：刚离开 recent 窗口的 token(token_id-M) 需从 FP16 重新量化
//     （requant_valid/requant_ptr）。
//   - num_tokens 饱和在 T；cache 满后新 token 覆盖最旧 slot（隐式驱逐）。
//   - reset_req 清空（新请求）。
//
// prefill/decode 对控制机透明（都是 new_token 脉冲）；因果 mask 由读侧用 num_tokens。
// 数据通路（FP16<->量化搬移）由后续 DDR/KV-002 冻结后接入本模块的命令。
// ============================================================================
module kv_rpc_ctrl #(
    parameter T     = 256,   // cache 深度（2 的幂）
    parameter M     = 32,    // recent FP16 tail 长度（M < T）
    parameter LOG_T = 8      // log2(T)
)(
    input  wire clk,
    input  wire rst_n,
    input  wire new_token,           // 脉冲：新 token 的 KV 到达
    input  wire reset_req,           // 脉冲：新请求，清空 cache
    output reg  [15:0] token_id,     // 已写 token 数（下一个 token 的绝对索引）
    output reg  [LOG_T:0] num_tokens,// 有效 token 数 0..T
    output wire [LOG_T-1:0] head,        // 环形写指针 = token_id mod T
    output wire [LOG_T-1:0] requant_ptr, // 需重量化的 slot = (token_id - M) mod T
    output wire requant_valid
);
    wire [15:0] token_minus_m = token_id - M;

    assign head         = token_id[LOG_T-1:0];
    assign requant_ptr  = token_minus_m[LOG_T-1:0];
    assign requant_valid = new_token && (token_id >= M) && (M < T);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            token_id   <= 16'd0;
            num_tokens <= {(LOG_T+1){1'b0}};
        end else begin
            if (reset_req) begin
                token_id   <= 16'd0;
                num_tokens <= {(LOG_T+1){1'b0}};
            end else if (new_token) begin
                token_id <= token_id + 1'b1;
                if (num_tokens < T)
                    num_tokens <= num_tokens + 1'b1;
            end
        end
    end

endmodule

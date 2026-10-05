`timescale 1ns/1ps
// ============================================================================
// kv_store_fsm.v —— KV cache 数据通路骨架（BRAM 模拟 DDR，DDR-002 的时序骨架）
//
// 串行状态机：写新 token ->（recent 边界）重新量化 -> 读。存储后端用 BRAM 模拟
// DDR，地址由 kv_addr_map 生成，token 计数/requant 命令由 kv_rpc_ctrl 生成。
//
// 占位（待接入，对应 UNKNOWN）：
//   - 写数据源：真实来自 PCIe，此处写确定性占位值 tkn*4096+cnt；
//   - 重新量化：真实是 min/max -> scale_calc -> kv_quant -> 写 codes+scale+min，
//     此处只打 qflag 标记（quant/dequant 算子已单独验证，接入即换）。
// 真实尺寸 G=3/D=64/T=256；骨架用小参数仿真。
// ============================================================================
module kv_store_fsm #(
    parameter G = 2,     // KV 头数
    parameter D = 4,     // head_dim（骨架小值）
    parameter T = 4      // context（骨架小值，2 的幂）
)(
    input  wire clk,
    input  wire rst_n,
    input  wire new_token,       // 脉冲：新 token 到达
    input  wire reset_req,       // 脉冲：清空
    input  wire rd_req,          // 脉冲：读请求
    input  wire [7:0] rd_g,      // 读哪个 KV 头
    input  wire [7:0] rd_slot,   // 读哪个 slot（token mod T）
    input  wire       rd_isK,    // 1=K 0=V
    output reg  rd_valid,        // 读数据有效（D 拍）
    output reg  [15:0] rd_data,
    output wire busy             // 1=正在写/requant/读
);
    localparam LOG_T = 2;        // T=4
    localparam DEPTH = G*T*2*D + G*T*4;   // data 区 + meta 区
    reg [15:0] mem [0:DEPTH-1];
    reg [0:G*T-1] qflag;         // 每 (g,t) 的量化标记（占位）

    // RPC 控制（token 计数 + requant 命令）
    wire [15:0] token_id;
    wire [LOG_T-1:0] head, requant_ptr;
    wire requant_valid;
    kv_rpc_ctrl #(.T(T), .M(T/2), .LOG_T(LOG_T)) u_ctrl (
        .clk(clk), .rst_n(rst_n), .new_token(new_token), .reset_req(reset_req),
        .token_id(token_id), .num_tokens(), .head(head),
        .requant_ptr(requant_ptr), .requant_valid(requant_valid));

    localparam S_IDLE = 3'd0, S_WR = 3'd1, S_REQ = 3'd2, S_RD = 3'd3;
    reg [2:0]  state;
    reg [15:0] cnt;         // 元素计数
    reg [7:0]  slot_r, g_r;
    reg [15:0] tkn;         // 当前写入 token 的索引
    reg        req_pending; // 写完后是否需要 requant

    // 写地址：扁平元素索引 cnt -> (g, isK*D+d)
    wire [15:0] wg   = cnt / (2*D);
    wire [15:0] wrem = cnt % (2*D);
    wire [31:0] wr_addr = wg*T*2*D + slot_r*2*D + wrem;
    // 读地址
    wire [31:0] rd_addr = g_r*T*2*D + slot_r*2*D + (rd_isK ? 0 : D) + cnt;

    integer i;
    initial begin
        for (i = 0; i < DEPTH; i = i + 1) mem[i] = 16'd0;
        qflag = 0;
    end

    assign busy = (state != S_IDLE);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= S_IDLE; cnt <= 0; slot_r <= 0; g_r <= 0; tkn <= 0;
            req_pending <= 0; rd_valid <= 0; rd_data <= 0;
        end else begin
            rd_valid <= 0;
            case (state)
                S_IDLE: begin
                    if (new_token) begin
                        slot_r <= head;
                        tkn <= token_id;          // 该 token 的绝对索引
                        req_pending <= requant_valid;
                        cnt <= 0;
                        state <= S_WR;
                    end else if (rd_req) begin
                        g_r <= rd_g; slot_r <= rd_slot; cnt <= 0;
                        state <= S_RD;
                    end
                end

                S_WR: begin
                    mem[wr_addr] <= tkn*4096 + cnt;   // 占位写数据
                    if (cnt == G*2*D - 1) begin
                        if (req_pending) begin g_r <= 0; state <= S_REQ; end
                        else state <= S_IDLE;
                    end else cnt <= cnt + 1'b1;
                end

                S_REQ: begin
                    qflag[g_r*T + slot_r] <= 1'b1;    // 占位：打量化标记
                    if (g_r == G-1) state <= S_IDLE;
                    else g_r <= g_r + 1'b1;
                end

                S_RD: begin
                    rd_valid <= 1'b1;
                    rd_data <= mem[rd_addr];
                    if (cnt == D-1) state <= S_IDLE;
                    else cnt <= cnt + 1'b1;
                end
            endcase
        end
    end

endmodule

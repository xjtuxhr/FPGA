`timescale 1ns/1ps
// ============================================================================
// kv_ops_top.v —— 算子库综合冒烟测试顶层（仅综合/资源评估用，不上板）
//
// 实例化 fpga/rtl 下所有算子，用内部自由计数器 stim 驱动输入。
// 各算子输出经 XOR 归约成一个 32-bit status 端口，既保持所有逻辑不被
// 优化掉，又控制 IO 数量（PH1A90SEG324 最多 148 IO）。
// 参数用小尺寸（D=8, T=4）先做「能否综合」冒烟测试；真实资源评估再放大。
// ============================================================================
module kv_ops_top (
    input  wire clk,
    input  wire rst_n,
    output wire [31:0] status
);

    // 自由计数器作激励
    reg [15:0] stim;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) stim <= 16'd0;
        else        stim <= stim + 16'd1;
    end

    wire signed [15:0] s16      = $signed(stim);
    wire        [15:0] stim_rev = {stim[7:0], stim[15:8]};

    // ---- 各算子输出（内部信号）----
    wire [3:0]  o_quant_q;
    wire [15:0] o_dequant_x;
    wire [15:0] o_mm_min, o_mm_max;
    wire [15:0] o_scale_inv;
    wire [31:0] o_pack;
    wire [3:0]  o_unpack_q, o_unpack_pos;
    wire [31:0] o_dp_result, o_ws_out;
    wire [15:0] o_sm_prob;
    wire [31:0] o_att_out, o_gqa_out;

    // ================= 量化链 =================
    kv_quant #(.Q_BITS(4), .X_W(16), .INV_W(16)) u_quant (
        .clk(clk), .rst_n(rst_n), .valid_in(stim[0]), .x(s16), .min(16'sd0),
        .inv_scale(16'd256), .valid_out(), .q(o_quant_q));

    kv_dequant #(.Q_BITS(4), .SCALE_W(16), .MIN_W(16), .OUT_W(16)) u_dequant (
        .clk(clk), .rst_n(rst_n), .valid_in(stim[0]), .q(o_quant_q),
        .scale(16'd256), .min(16'sd0), .valid_out(), .x(o_dequant_x));

    min_max_reduce #(.DATA_W(16), .GROUP_SIZE(32)) u_mm (
        .clk(clk), .rst_n(rst_n), .valid_in(stim[0]), .value(s16),
        .group_done(), .min_out(o_mm_min), .max_out(o_mm_max));

    scale_calc #(.Q_BITS(4), .X_W(16)) u_scale (
        .clk(clk), .rst_n(rst_n), .start(stim[0]), .max(s16), .min(16'sd0),
        .done(), .inv_scale(o_scale_inv));

    // ================= 3-bit 特例 =================
    kv_pack_3bit u_pack (
        .clk(clk), .rst_n(rst_n), .valid_in(stim[0]), .q_in(stim[3:0]),
        .valid_out(), .packed(o_pack));

    kv_unpack_3bit u_unpack (
        .clk(clk), .rst_n(rst_n), .valid_in(stim[0]), .packed(o_pack),
        .valid_out(), .q_out(o_unpack_q), .pos(o_unpack_pos));

    // ================= attention 算子 =================
    dot_product #(.LEN(8), .DATA_W(16)) u_dp (
        .clk(clk), .rst_n(rst_n), .valid_in(stim[0]), .a(s16), .b($signed(stim_rev)),
        .valid_out(), .result(o_dp_result));

    weighted_sum #(.T(4), .D(8), .P_W(16), .V_W(16)) u_ws (
        .clk(clk), .rst_n(rst_n), .start(stim[0]), .p_valid(stim[1]), .p(stim),
        .v_valid(stim[2]), .v(s16), .out_valid(), .out(o_ws_out), .out_idx());

    softmax #(.T(8), .SCORE_W(16)) u_sm (
        .clk(clk), .rst_n(rst_n), .start(stim[0]), .valid_in(stim[1]), .score(s16),
        .valid_out(), .prob(o_sm_prob));

    attention #(.T(4), .D(8), .DATA_W(16)) u_att (
        .clk(clk), .rst_n(rst_n), .start(stim[0]),
        .q_valid(stim[1]), .q_in(s16),
        .k_valid(stim[2]), .k_in($signed(stim_rev)),
        .v_valid(stim[3]), .v_in(s16),
        .out_valid(), .out(o_att_out));

    gqa_attention #(.H(4), .G(2), .D(8), .T(4), .DATA_W(16)) u_gqa (
        .clk(clk), .rst_n(rst_n), .start(stim[0]),
        .q_valid(stim[1]), .q_in(s16),
        .k_valid(stim[2]), .k_in($signed(stim_rev)),
        .v_valid(stim[3]), .v_in(s16),
        .out_valid(), .out(o_gqa_out), .out_head(), .out_d());

    // ---- XOR 归约，把全部输出压成一个 32-bit 状态字，防止逻辑被优化 ----
    assign status =
        ({28'd0, o_quant_q}  ^ {16'd0, o_dequant_x} ^ {16'd0, o_mm_min} ^
         {16'd0, o_mm_max}   ^ {16'd0, o_scale_inv} ^ o_pack ^
         {28'd0, o_unpack_q} ^ {28'd0, o_unpack_pos} ^ o_dp_result ^
         o_ws_out            ^ {16'd0, o_sm_prob}    ^ o_att_out ^ o_gqa_out);

endmodule

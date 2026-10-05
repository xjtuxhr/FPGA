`timescale 1ns/1ps
// ============================================================================
// kv_3bit_tb.v —— 3-bit 打包/解包 round-trip 自校验 testbench
//
// 验证：11 个量化值（前10个3-bit，第11个2-bit）打包成 32-bit 字，
//       再解包回来，逐元素一致；并抽查一个已知打包值的位布局。
// ============================================================================
module kv_3bit_tb;

    reg clk = 0, rst_n = 0;
    reg pack_valid = 0;
    reg [3:0] q_in = 0;
    wire pack_valid_out;
    wire [31:0] packed;

    reg unpack_valid = 0;
    wire unpack_valid_out;
    wire [3:0] q_out;
    wire [3:0] pos;

    kv_pack_3bit u_pack (
        .clk(clk), .rst_n(rst_n), .valid_in(pack_valid), .q_in(q_in),
        .valid_out(pack_valid_out), .packed(packed)
    );
    kv_unpack_3bit u_unpack (
        .clk(clk), .rst_n(rst_n), .valid_in(unpack_valid), .packed(packed),
        .valid_out(unpack_valid_out), .q_out(q_out), .pos(pos)
    );

    always #5 clk = ~clk;

    integer i, errors = 0;
    reg [3:0] expect [0:10];

    // 打包 11 个值，等待 valid_out 脉冲，打印 packed
    task do_pack;
        begin
            for (i = 0; i < 11; i = i + 1) begin
                @(negedge clk);
                pack_valid <= 1'b1;
                q_in      <= expect[i];
            end
            @(negedge clk);
            pack_valid <= 1'b0;
            @(posedge clk);   // 确保 packed 已锁存
        end
    endtask

    // 解包并逐元素检查
    task do_unpack_check;
        begin
            @(negedge clk);
            unpack_valid <= 1'b1;
            @(negedge clk);
            unpack_valid <= 1'b0;
            for (i = 0; i < 11; i = i + 1) begin
                @(negedge clk);
                if (q_out !== expect[i] || pos !== i[3:0]) begin
                    errors = errors + 1;
                    $display("FAIL: pos=%0d q=%0d (expected pos=%0d q=%0d)",
                             pos, q_out, i, expect[i]);
                end else begin
                    $display("PASS: pos=%0d q=%0d", pos, q_out);
                end
            end
        end
    endtask

    initial begin
        #20 rst_n = 1'b1; #10;

        // ---- 组 1：round-trip，覆盖 3-bit 全范围 + 第 11 个 2-bit 上限 ----
        $display("== group 1: round-trip ==");
        expect[0]=1; expect[1]=2; expect[2]=3; expect[3]=4; expect[4]=5;
        expect[5]=6; expect[6]=7; expect[7]=0; expect[8]=1; expect[9]=2; expect[10]=3;
        do_pack;
        $display("  packed = 0x%08h", packed);
        do_unpack_check;

        // ---- 组 2：位布局抽查，q=[7,0,...,0,3] -> packed = 0xC0000007 ----
        $display("== group 2: bit layout ==");
        expect[0]=7; expect[1]=0; expect[2]=0; expect[3]=0; expect[4]=0;
        expect[5]=0; expect[6]=0; expect[7]=0; expect[8]=0; expect[9]=0; expect[10]=3;
        do_pack;
        $display("  packed = 0x%08h (expect 0xC0000007)", packed);
        if (packed !== 32'hC0000007) begin
            errors = errors + 1;
            $display("FAIL: packed bit layout wrong");
        end
        do_unpack_check;

        #20;
        if (errors == 0) $display("ALL PASSED"); else $display("%0d ERRORS", errors);
        $finish;
    end

endmodule

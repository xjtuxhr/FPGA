`timescale 1ns/1ps
// kv_store_fsm_tb.v —— KV cache 数据通路骨架自校验
// 写 6 个 token（T=4，覆盖回绕）-> 读回校验 -> 检查 requant 标记。
module kv_store_fsm_tb;
    parameter G = 2, D = 4, T = 4;
    reg clk = 0, rst_n = 0, new_token = 0, reset_req = 0, rd_req = 0;
    reg [7:0] rd_g = 0, rd_slot = 0;
    reg rd_isK = 0;
    wire rd_valid;
    wire [15:0] rd_data;
    wire busy;

    kv_store_fsm #(.G(G), .D(D), .T(T)) dut (
        .clk(clk), .rst_n(rst_n), .new_token(new_token), .reset_req(reset_req),
        .rd_req(rd_req), .rd_g(rd_g), .rd_slot(rd_slot), .rd_isK(rd_isK),
        .rd_valid(rd_valid), .rd_data(rd_data), .busy(busy));

    always #5 clk = ~clk;

    integer t, d, errors = 0;
    reg [15:0] expect;

    // 写一个 token
    task wr_token;
        begin
            @(negedge clk); new_token = 1'b1;
            @(negedge clk); new_token = 1'b0;
        end
    endtask

    // 读 (g, slot, isK)，期望 token 索引 tkn，校验 D 个字
    task rd_check(input integer g, slot, isK, tkn);
        integer dd;
        begin
            @(negedge clk); rd_req = 1'b1; rd_g = g; rd_slot = slot; rd_isK = isK;
            @(negedge clk); rd_req = 1'b0;
            for (dd = 0; dd < D; dd = dd + 1) begin
                @(posedge rd_valid);
                @(negedge clk);
                expect = tkn*4096 + (g*2*D + (isK ? 0 : D) + dd);
                if (rd_data !== expect) begin
                    errors = errors + 1;
                    if (errors <= 10)
                        $display("FAIL rd(g%0d slot%0d %s d%0d): %0d expect %0d",
                                 g, slot, isK ? "K" : "V", dd, rd_data, expect);
                end
            end
        end
    endtask

    initial begin
        #20 rst_n = 1'b1; #10;

        // 写 token 0..5（T=4，回绕一次半）
        for (t = 0; t < 6; t = t + 1) begin
            wr_token;
            @(negedge clk);                       // 等 busy 回落
            wait (busy === 0);
            @(negedge clk);
        end

        // 读回 slot0(=token4) 和 slot1(=token5) 的 K/V，各 2 个头
        rd_check(0, 0, 1, 4);   // g0 slot0 K = token4
        rd_check(0, 0, 0, 4);   // g0 slot0 V
        rd_check(1, 0, 1, 4);   // g1 slot0 K
        rd_check(0, 1, 1, 5);   // g0 slot1 K = token5
        rd_check(1, 1, 0, 5);   // g1 slot1 V

        // 检查 requant 标记：token 0..3 都触发过 requant，全部 slot 的 qflag 应为 1
        for (t = 0; t < G*T; t = t + 1) begin
            if (dut.qflag[t] !== 1'b1) begin
                errors = errors + 1;
                $display("FAIL qflag[%0d] = %0d expect 1", t, dut.qflag[t]);
            end
        end

        if (errors == 0) $display("kv_store_fsm: ALL checks PASSED");
        else $display("kv_store_fsm: %0d ERRORS", errors);
        $finish;
    end
endmodule

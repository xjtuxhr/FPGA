`timescale 1ns/1ps
// kv_rpc_ctrl_tb.v —— RPC tail 控制状态机自校验
// 验证：写指针回绕、requant 触发边界（token_id>=M）、num_tokens 饱和、reset。
// 激励：new_token 在 negedge 置 1，下个 negedge 清 0（跨过中间 posedge 被采样）。
module kv_rpc_ctrl_tb;
    parameter T = 256, M = 32, LOG_T = 8;
    reg clk = 0, rst_n = 0, new_token = 0, reset_req = 0;
    wire [15:0] token_id;
    wire [LOG_T:0] num_tokens;
    wire [LOG_T-1:0] head, requant_ptr;
    wire requant_valid;

    kv_rpc_ctrl #(.T(T), .M(M), .LOG_T(LOG_T)) dut (
        .clk(clk), .rst_n(rst_n), .new_token(new_token), .reset_req(reset_req),
        .token_id(token_id), .num_tokens(num_tokens), .head(head),
        .requant_ptr(requant_ptr), .requant_valid(requant_valid));

    always #5 clk = ~clk;

    integer i, errors = 0;
    integer exp_head, exp_req_ptr;
    reg exp_req_valid;

    initial begin
        #20 rst_n = 1'b1; #10;

        // ---- 1) 连续写 700 个 token（覆盖 2 次回绕 + M 边界 + 饱和）----
        for (i = 0; i < 700; i = i + 1) begin
            @(negedge clk); new_token = 1'b1;
            #1;
            // 此刻 token_id == i（本次 new_token 尚未被 posedge 采样）
            exp_head = i % T;
            exp_req_valid = (i >= M) && (M < T);
            if (head !== exp_head[LOG_T-1:0]) begin
                errors = errors + 1;
                if (errors <= 10) $display("FAIL head@%0d: %0d expect %0d", i, head, exp_head);
            end
            if (requant_valid !== exp_req_valid) begin
                errors = errors + 1;
                if (errors <= 10) $display("FAIL req_valid@%0d: %0d expect %0d", i, requant_valid, exp_req_valid);
            end
            if (exp_req_valid) begin
                exp_req_ptr = (i - M) % T;
                if (requant_ptr !== exp_req_ptr[LOG_T-1:0]) begin
                    errors = errors + 1;
                    if (errors <= 10) $display("FAIL req_ptr@%0d: %0d expect %0d", i, requant_ptr, exp_req_ptr);
                end
            end
            @(negedge clk); new_token = 1'b0;
            #1;
        end

        if (num_tokens !== T) begin
            errors = errors + 1;
            $display("FAIL num_tokens saturate: %0d expect %0d", num_tokens, T);
        end

        // ---- 2) reset 清空 ----
        @(negedge clk); reset_req = 1'b1;
        @(negedge clk); reset_req = 1'b0;
        #1;
        if (token_id !== 0 || num_tokens !== 0) begin
            errors = errors + 1;
            $display("FAIL reset: token_id=%0d num=%0d", token_id, num_tokens);
        end

        // ---- 3) reset 后重写 M+3 个 token，验证 M 边界重新开始 ----
        for (i = 0; i < M+3; i = i + 1) begin
            @(negedge clk); new_token = 1'b1;
            #1;
            exp_req_valid = (i >= M) && (M < T);
            if (requant_valid !== exp_req_valid) begin
                errors = errors + 1;
                if (errors <= 10) $display("FAIL post-reset req_valid@%0d: %0d expect %0d", i, requant_valid, exp_req_valid);
            end
            if (exp_req_valid) begin
                exp_req_ptr = (i - M) % T;
                if (requant_ptr !== exp_req_ptr[LOG_T-1:0]) begin
                    errors = errors + 1;
                    if (errors <= 10) $display("FAIL post-reset req_ptr@%0d: %0d expect %0d", i, requant_ptr, exp_req_ptr);
                end
            end
            @(negedge clk); new_token = 1'b0;
            #1;
        end

        if (errors == 0) $display("kv_rpc_ctrl: ALL checks PASSED");
        else $display("kv_rpc_ctrl: %0d ERRORS", errors);
        $finish;
    end
endmodule

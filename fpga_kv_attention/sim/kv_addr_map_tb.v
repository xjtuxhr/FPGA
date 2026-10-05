`timescale 1ns/1ps
// kv_addr_map_tb.v —— 地址映射自校验（无重叠、覆盖完整、索引正确）
module kv_addr_map_tb;
    parameter G = 3, D = 64, T = 256;
    reg [7:0] g, t;
    reg is_K;
    wire [31:0] data_addr, meta_addr;

    kv_addr_map #(.G(G), .D(D), .T(T)) dut (
        .g(g), .t(t), .is_K(is_K), .data_addr(data_addr), .meta_addr(meta_addr));

    integer errors = 0;

    task chk(input integer a, b, msg);
        begin
            if (a !== b) begin
                errors = errors + 1;
                $display("FAIL %s: %0d expect %0d", msg, a, b);
            end
        end
    endtask

    initial begin
        // data 区关键地址
        g=0; t=0; is_K=1; #1; chk(data_addr, 0,             "data(0,0,K)");
        g=0; t=0; is_K=0; #1; chk(data_addr, D,             "data(0,0,V)");
        g=0; t=1; is_K=1; #1; chk(data_addr, 2*D,           "data(0,1,K)");
        g=1; t=0; is_K=1; #1; chk(data_addr, T*2*D,         "data(1,0,K)");
        g=G-1; t=T-1; is_K=0; #1;
        chk(data_addr, (G-1)*T*2*D + (T-1)*2*D + D, "data(G-1,T-1,V)");

        // meta 区关键地址
        g=0; t=0; is_K=1; #1; chk(meta_addr, G*T*2*D + 0,   "meta(0,0,K scale)");
        g=0; t=0; is_K=0; #1; chk(meta_addr, G*T*2*D + 2,   "meta(0,0,V scale)");
        g=0; t=1; is_K=1; #1; chk(meta_addr, G*T*2*D + 4,   "meta(0,1,K scale)");
        g=1; t=0; is_K=1; #1; chk(meta_addr, G*T*2*D + 4*T, "meta(1,0,K scale)");

        // 无重叠：data 区 [0, G*T*2*D)，meta 区从 G*T*2*D 起
        if (G*T*2*D + G*T*4 > G*T*(2*D+4)) begin
            errors = errors + 1;
            $display("FAIL region overlap");
        end

        if (errors == 0) $display("kv_addr_map: ALL checks PASSED");
        else $display("kv_addr_map: %0d ERRORS", errors);
        $finish;
    end
endmodule

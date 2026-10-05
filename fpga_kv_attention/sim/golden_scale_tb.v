`timescale 1ns/1ps
// ============================================================================
// golden_scale_tb.v —— scale_calc 软硬件对拍 testbench
// 读 golden/scale.hex（每行 64-bit），喂 max/min，比对 inv_scale。
// ============================================================================
module golden_scale_tb;

    parameter N = 1000;

    reg [63:0] vec [0:N-1];
    reg clk = 0, rst_n = 0, start = 0;
    reg signed [15:0] max = 0;
    reg signed [15:0] min = 0;
    wire done;
    wire [15:0] inv_scale;

    scale_calc #(.Q_BITS(4), .X_W(16))
        dut (.clk(clk), .rst_n(rst_n), .start(start),
             .max(max), .min(min), .done(done), .inv_scale(inv_scale));

    always #5 clk = ~clk;

    integer i, errors = 0;

    initial begin
        $readmemh("golden/scale.hex", vec);
        #20 rst_n = 1'b1; #10;
        for (i = 0; i < N; i = i + 1) begin
            @(negedge clk);
            start <= 1'b1;
            max   <= vec[i][15:0];
            min   <= vec[i][31:16];
            @(negedge clk);
            start <= 1'b0;
            wait (done == 1'b1);          // 等除法完成（约 17 拍）
            @(negedge clk);
            if (inv_scale !== vec[i][47:32]) begin
                errors = errors + 1;
                if (errors <= 10)
                    $display("FAIL i=%0d: max=%0d min=%0d -> inv=%0d exp=%0d",
                             i, $signed(vec[i][15:0]), $signed(vec[i][31:16]),
                             inv_scale, vec[i][47:32]);
            end
        end
        #20;
        if (errors == 0) $display("golden_scale: ALL %0d PASSED", N);
        else $display("golden_scale: %0d ERRORS / %0d", errors, N);
        $finish;
    end

endmodule

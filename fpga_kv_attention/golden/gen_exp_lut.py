#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# gen_exp_lut.py —— 生成 softmax 的 exp 查找表（NUM-003 校准）
#
# 设计：256 条目，覆盖 exp 输入 x ∈ [-7.97, 0]（约 [-8,0]），输出 Q0.16。
#   地址映射：addr = (-x) >> 3（x 为 Q8.8 有符号，负值表示低于 max 的分差），
#             LUT[addr] = round(exp(-addr/32) * 2^16)。
#   输出：exp_lut.v（Verilog case ROM）+ golden/exp_lut.hex（对拍）。
# ============================================================================
import math

N = 256          # 8-bit 地址
OUT_FRAC = 16    # Q0.16 输出


def gen_vals():
    vals = []
    for addr in range(N):
        x = -addr / 32.0                  # exp 输入 ∈ [-7.97, 0]
        v = int(round(math.exp(x) * (1 << OUT_FRAC)))
        v = max(0, min((1 << OUT_FRAC) - 1, v))   # clamp 到 16-bit
        vals.append(v)
    return vals


def main():
    vals = gen_vals()

    with open("rtl/exp_lut.v", "w") as f:
        f.write("`timescale 1ns/1ps\n")
        f.write("// ============================================================================\n")
        f.write("// exp_lut.v —— exp 查找表（自动生成，NUM-003 校准）\n")
        f.write("// 范围 x ∈ [-7.97, 0]，256 条目，输出 Q0.16（值 = val/2^16）\n")
        f.write("// 地址：addr = (-x) >> 3，x 为 Q8.8（softmax 中 x = score - max <= 0）\n")
        f.write("// ============================================================================\n")
        f.write("module exp_lut (\n")
        f.write("    input  wire [7:0] addr,   // 0..255\n")
        f.write("    output reg  [15:0] val    // exp(x)*2^16\n")
        f.write(");\n")
        f.write("    always @(*) begin\n")
        f.write("        case (addr)\n")
        for i, v in enumerate(vals):
            f.write(f"            8'd{i}: val = 16'd{v};\n")
        f.write("            default: val = 16'd0;\n")
        f.write("        endcase\n")
        f.write("    end\n")
        f.write("endmodule\n")

    with open("golden/exp_lut.hex", "w") as f:
        for v in vals:
            f.write(f"{v:04x}\n")

    # 打印几个关键点供人工核对
    for addr in (0, 32, 64, 128, 192, 255):
        x = -addr / 32.0
        print(f"  addr={addr:3d}: x={x:6.3f}  exp={math.exp(x):.6f}  val={vals[addr]:5d}")

    print(f"generated rtl/exp_lut.v ({N} entries) + golden/exp_lut.hex")


if __name__ == "__main__":
    main()

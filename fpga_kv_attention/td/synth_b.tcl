# ============================================================================
# synth_b.tcl —— Attention-only B 通路综合（资源 + 时序）
# 用法：td_commands_prompt.exe synth_b.tcl
# ============================================================================
puts "==== Attention-only B synthesis (H=9/G=3/D=64/T=64) ===="

import_device ph1_90.db -package PH1A90SEG324 -speed 2

read_hdl -file {
  E:/KVmix/fpga/rtl/attention.v
  E:/KVmix/fpga/rtl/gqa_attention.v
  E:/KVmix/fpga/rtl/exp_lut.v
  E:/KVmix/fpga/rtl/div_u32_u32.v
  E:/KVmix/fpga/rtl/fp16_to_q88.v
  E:/KVmix/fpga/rtl/attention_b_top.v
  E:/KVmix/fpga/rtl/attention_b_synth.v
} -top attention_b_synth
puts "hdl read"

read_sdc E:/KVmix/fpga/td/timing.sdc

optimize_rtl
optimize_gate
report_area -file E:/KVmix/fpga/td/attention_b_gate.area
update_timing
report_timing_summary -file E:/KVmix/fpga/td/attention_b.timing

puts "==== B synthesis finished ===="
exit

# ============================================================================
# synth_gqa.tcl —— GQA attention 真实尺寸综合（资源 + 时序）
# 用法（设置 T 后批处理）：
#   GQA_T=64  td_commands_prompt.exe synth_gqa.tcl
#   GQA_T=128 td_commands_prompt.exe synth_gqa.tcl
#   GQA_T=256 td_commands_prompt.exe synth_gqa.tcl
# ============================================================================

set T   $::env(GQA_T)
set top "gqa_synth_t${T}"
set area_gate "E:/KVmix/fpga/td/gqa_t${T}_gate.area"
set timing     "E:/KVmix/fpga/td/gqa_t${T}.timing"

puts "==== GQA synthesis: T=${T}, top=${top} ===="

import_device ph1_90.db -package PH1A90SEG324 -speed 2

read_hdl -file {
  E:/KVmix/fpga/rtl/attention.v
  E:/KVmix/fpga/rtl/gqa_attention.v
  E:/KVmix/fpga/rtl/exp_lut.v
  E:/KVmix/fpga/rtl/div_u32_u32.v
  E:/KVmix/fpga/rtl/gqa_synth_t64.v
  E:/KVmix/fpga/rtl/gqa_synth_t128.v
  E:/KVmix/fpga/rtl/gqa_synth_t256.v
} -top $top
puts "hdl read"

read_sdc E:/KVmix/fpga/td/timing.sdc

optimize_rtl
optimize_gate
report_area -file $area_gate
update_timing
report_timing_summary -file $timing

puts "==== T=${T} synthesis finished ===="
exit

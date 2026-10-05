# ============================================================================
# synth_all_ops.tcl —— KVmix 算子库综合冒烟测试（TD 批处理）
# 用法：td_commands_prompt.exe synth_all_ops.tcl
# 只跑到综合（optimize_rtl + optimize_gate），不做布局布线。
# ============================================================================

puts "==== KVmix operators synthesis smoke test ===="

import_device ph1_90.db -package PH1A90SEG324 -speed 2
puts "device imported"

read_hdl -file {
  E:/KVmix/fpga/rtl/kv_quant.v
  E:/KVmix/fpga/rtl/kv_dequant.v
  E:/KVmix/fpga/rtl/min_max_reduce.v
  E:/KVmix/fpga/rtl/scale_calc.v
  E:/KVmix/fpga/rtl/div_u32_u16.v
  E:/KVmix/fpga/rtl/div_u32_u32.v
  E:/KVmix/fpga/rtl/kv_pack_3bit.v
  E:/KVmix/fpga/rtl/kv_unpack_3bit.v
  E:/KVmix/fpga/rtl/exp_lut.v
  E:/KVmix/fpga/rtl/dot_product.v
  E:/KVmix/fpga/rtl/weighted_sum.v
  E:/KVmix/fpga/rtl/softmax.v
  E:/KVmix/fpga/rtl/attention.v
  E:/KVmix/fpga/rtl/gqa_attention.v
  E:/KVmix/fpga/rtl/kv_ops_top.v
} -top kv_ops_top
puts "hdl read"

optimize_rtl
report_area -file E:/KVmix/fpga/td/kv_ops_rtl.area
puts "optimize_rtl done"

optimize_gate
report_area -file E:/KVmix/fpga/td/kv_ops_gate.area
puts "optimize_gate done"

puts "==== synthesis finished ===="
exit

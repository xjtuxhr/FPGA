# 25MHz 板级时钟（FPGA_SYSCLK @ T16），周期 40ns
create_clock -period 40.000 -name clk [get_ports clk]

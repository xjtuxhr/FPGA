create_clock -name {sysclk} -period 40.000 -waveform {0.000 20.000} [get_ports {I_sysclk}]
derive_clocks
rename_clock -name {clk0} [get_clocks {U_pll/pll_inst.clkc[0]}]

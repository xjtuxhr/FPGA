# Reference
#create_clock -name ddr_ref_clk -period 10 -waveform {0 5} [get_pins {u_clk/u_pll0/pll_inst.refclk}]
derive_clocks

# PLL0
rename_clock -name ref_clk [get_clocks {u_ddrmc_top/u_ddr_phy/u_ddrphy_clk_gen/u_ddrphy_pll0/pll_inst.clkc[0]}]
rename_clock -name mcu_clk [get_clocks {u_ddrmc_top/u_ddr_phy/u_ddrphy_clk_gen/u_ddrphy_pll0/pll_inst.clkc[3]}]

# PLL1
rename_clock -name dfi_clk [get_clocks {u_ddrmc_top/u_ddr_phy/u_ddrphy_clk_gen/u_ddrphy_pll1/pll_inst.clkc[0]}]

set_clock_groups -asynchronous -group [get_clocks mcu_clk]
set_clock_groups -asynchronous -group [get_clocks dfi_clk]
set_clock_uncertainty -setup 0.1 [get_clocks mcu_clk]

###################################################################################################
# Exception Constraint for Bus Matrix
###################################################################################################
# ZQCAL
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.zqcal_clrcfg}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.zqcal_start}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.zqcal_update_en}]

# DCC
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_dcc_clrcfg}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_dcc_start}]

# MDL
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_delay_cal_mode}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_delay_cal_clk_en[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_delay_cal_en_in[*]}]

# MISC
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_dqs_pupd_en}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_bank/bkIdx*bk_used$u_ddrbank_top/u_ddrbank.*_wrlvl_mode}]

# PPC
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.zqcal_done_bank[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.dcc_done_bank[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.delay_cal_en_in_upp[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.delay_cal_in_upp[*]}]
set_false_path -to [get_pins {u_ddrmc_top/u_ddr_phy/u_ddrphy_top/u_ddrphy_ppc/u_ddrppc.wrlvl_qin[*]}]



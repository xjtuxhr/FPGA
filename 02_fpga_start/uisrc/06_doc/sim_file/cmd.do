## part 1: create lib
vlib work
vmap work work

## part 2: load rtl
vlog -timescale 1ps/1ps -sv -f   compile.f                                                                      
                                                       
## part 3: sim
vsim -L C:/modeltech64_10.6d/anlogic/PH1 -gui -novopt work.sim_top_tb
#vsim -voptargs=+acc work.pll_test_tb         

## part 4: add wave
#do wave.do
add wave *

## part 5: show ui
view wave
view structure
view signals

## part 6: run sim
#run -all
run 1000ns



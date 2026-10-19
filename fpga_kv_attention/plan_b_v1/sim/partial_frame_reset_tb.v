`timescale 1ns/1ps
module partial_frame_reset_tb;
    reg usr_clk=0, dfi_clk=0;
    always #4 usr_clk=~usr_clk;
    always #3 dfi_clk=~dfi_clk;
    reg usr_rst_n=0, dfi_rst_n=0, ddr_ready=0;
    reg reset_req=0, accept_new=1;
    reg [127:0] hdata=0;
    reg hvalid=0, hlast=0, cready=1;
    wire hready, cvalid, clast, bridge_ready, endpoint_idle, request_start;
    wire axi_safe, quiesce_seen, frame_active, reset_active, block_new;
    wire [127:0] cdata;
    wire [15:0] ckeep, cuser;
    integer ack_beats=0, resets=0, starts=0;

    planb_reset_guard #(.RESET_CYCLES(8'd8)) guard (
        .clk(usr_clk), .rst_n(usr_rst_n), .soft_reset_req(reset_req),
        .session_abort_req(1'b0),
        .axi_quiescent(quiesce_seen && axi_safe),
        .bridge_ready(bridge_ready),
        .reset_active(reset_active), .block_new(block_new),
        .mask_endpoint_fault());
    v2_endpoint_cdc #(.MAX_T(8)) dut (
        .usr_clk(usr_clk), .usr_rst_n(usr_rst_n), .soft_reset(reset_active),
        .usr_accept_new(accept_new && !block_new),
        .usr_quiesce_req(block_new), .usr_quiesce_seen(quiesce_seen),
        .usr_request_start(request_start), .usr_frame_active(frame_active),
        .usr_bridge_ready(bridge_ready), .usr_endpoint_idle(endpoint_idle),
        .usr_axi_quiescent(axi_safe),
        .dfi_clk(dfi_clk), .dfi_rst_n(dfi_rst_n), .ddr_ready(ddr_ready),
        .m0_axis_h2c_tdata(hdata), .m0_axis_h2c_tkeep(16'hffff),
        .m0_axis_h2c_tuser(16'd0), .m0_axis_h2c_tvalid(hvalid),
        .m0_axis_h2c_tlast(hlast), .m0_axis_h2c_tready(hready),
        .s0_axis_c2h_tdata(cdata), .s0_axis_c2h_tkeep(ckeep),
        .s0_axis_c2h_tuser(cuser), .s0_axis_c2h_tvalid(cvalid),
        .s0_axis_c2h_tlast(clast), .s0_axis_c2h_tready(cready),
        .m_axi_awready(1'b0), .m_axi_arready(1'b0), .m_axi_wready(1'b0),
        .m_axi_bid(4'd0), .m_axi_rid(4'd0), .m_axi_bresp(2'd0),
        .m_axi_rresp(2'd0), .m_axi_bvalid(1'b0), .m_axi_rvalid(1'b0),
        .m_axi_rdata(128'd0), .m_axi_rlast(1'b0));
    always @(posedge usr_clk) if (usr_rst_n) begin
        if (request_start) starts=starts+1;
        if (reset_active && !resets) resets=1;
        if (cvalid && cready) begin
            if (cdata !== (ack_beats==0 ? 128'h00000000000000ff00010002584d564b :
                                          128'h00000000bd168fc50000000011223344))
                $fatal(1,"unexpected ACK beat %0d: %h",ack_beats,cdata);
            if (clast !== (ack_beats==1)) $fatal(1,"wrong TLAST");
            ack_beats=ack_beats+1;
        end
    end
    initial begin
        repeat(8) @(negedge usr_clk);
        usr_rst_n=1; dfi_rst_n=1; ddr_ready=1;
        wait(bridge_ready && endpoint_idle && axi_safe);
        // First beat only: parser cannot reach idle without intervention.
        @(negedge usr_clk);
        hdata=128'h00000000000000ff00010002584d564b;
        hlast=0; hvalid=1;
        @(posedge usr_clk); if (!hready) $fatal(1,"partial first beat blocked");
        @(negedge usr_clk); hvalid=0; reset_req=1;
        @(negedge usr_clk); reset_req=0;
        wait(reset_active);
        if (!quiesce_seen || !axi_safe) $fatal(1,"reset without DDR-side quiesce ACK");
        wait(!reset_active);
        wait(bridge_ready && endpoint_idle && !block_new);
        @(negedge usr_clk);
        if (frame_active || ack_beats != 0 || resets != 1)
            $fatal(1,"partial frame was not flushed");
        // Fresh valid RESET must produce exactly one 32-byte ACK.
        hdata=128'h00000000000000ff00010002584d564b;
        hlast=0; hvalid=1;
        @(posedge usr_clk); if (!hready) $fatal(1,"new RESET blocked");
        @(negedge usr_clk);
        hdata=128'h00000000bd168fc50000000011223344; hlast=1;
        @(posedge usr_clk); if (!hready) $fatal(1,"RESET tail blocked");
        @(negedge usr_clk); hvalid=0; hlast=0;
        wait(ack_beats==2);
        repeat(20) @(negedge usr_clk);
        if (starts != 2 || ack_beats != 2 || !endpoint_idle)
            $fatal(1,"ghost response or stale frame starts=%0d beats=%0d",starts,ack_beats);
        $display("partial_frame_reset: PASS");
        $finish;
    end
    initial begin #100000; $fatal(1,"partial frame reset watchdog"); end
endmodule

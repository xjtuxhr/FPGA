`timescale 1ns/1ps
module cdc_ready_gate_tb;
    reg usr_clk=0, dfi_clk=0;
    always #4 usr_clk=~usr_clk;
    always #3 dfi_clk=~dfi_clk;
    reg usr_rst_n=0, dfi_rst_n=0, ddr_ready=0, accept_new=0;
    reg [127:0] hdata=0;
    reg hvalid=0, hlast=0, cready=0;
    wire hready, cvalid, clast, request_start, response_ready;
    wire bridge_ready, endpoint_idle, axi_safe, frame_active;
    wire [127:0] cdata;
    wire [15:0] ckeep, cuser;
    integer starts=0, dones=0, beats=0, stage=0;
    v2_endpoint_cdc #(.MAX_T(8)) dut (
        .usr_clk(usr_clk), .usr_rst_n(usr_rst_n), .soft_reset(1'b0),
        .usr_accept_new(accept_new), .usr_request_start(request_start),
        .usr_quiesce_req(1'b0), .usr_quiesce_seen(),
        .usr_response_ready(response_ready), .usr_frame_active(frame_active),
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
        if (response_ready) dones=dones+1;
        if (cvalid && cready) begin
            if (cdata !== (beats==0 ? 128'h00000000000000ff00010002584d564b :
                                      128'h00000000bd168fc50000000011223344))
                $fatal(1,"bad ACK beat %0d: %h",beats,cdata);
            if (clast !== (beats==1)) $fatal(1,"bad TLAST beat %0d",beats);
            beats=beats+1;
        end
    end
    initial begin
        repeat(8) @(negedge usr_clk);
        usr_rst_n=1; dfi_rst_n=1; ddr_ready=1;
        stage=1;
        wait(bridge_ready && endpoint_idle && axi_safe);
        stage=2;
        @(negedge usr_clk); hdata=128'h00000000000000ff00010002584d564b;
        hlast=0; hvalid=1;
        repeat(5) begin
            @(posedge usr_clk); if (hready) $fatal(1,"H2C accepted without READY");
        end
        @(negedge usr_clk); accept_new=1;
        stage=3;
        @(posedge usr_clk); if (!hready) $fatal(1,"first beat blocked");
        @(negedge usr_clk); accept_new=0;
        hdata=128'h00000000bd168fc50000000011223344; hlast=1;
        @(posedge usr_clk); if (!hready || !frame_active) $fatal(1,"tail beat blocked");
        @(negedge usr_clk); hvalid=0; hlast=0;
        stage=4;
        wait(dones==1);
        stage=5;
        @(negedge usr_clk);
        if (starts!=1 || dones!=1 || beats!=0) $fatal(1,"READY/DONE before drain starts=%0d done=%0d beats=%0d",starts,dones,beats);
        cready=1;
        stage=6;
        wait(beats==2);
        @(negedge usr_clk); cready=0;
        if (starts!=1 || dones!=1) $fatal(1,"duplicate event");
        $display("cdc_ready_gate: PASS");
        $finish;
    end
    initial begin #100000; $fatal(1,"watchdog stage=%0d bridge=%b idle=%b axi=%b hready=%b cvalid=%b starts=%0d dones=%0d beats=%0d epstate=%0d fault=%b err=%0d h2c_v=%b h2c_r=%b frame=%b",stage,bridge_ready,endpoint_idle,axi_safe,hready,cvalid,starts,dones,beats,dut.u_ep.state,dut.u_ep.fault,dut.u_ep.error_code,dut.h2c_rvalid,dut.h2c_rready,dut.usr_in_frame); end
endmodule

`timescale 1ns/1ps
// A queued RESET ACK must vanish on BAR soft reset; a new RESET then works.
module planb_soft_reset_cdc_tb;
    reg usr_clk=0, dfi_clk=0;
    always #4 usr_clk=~usr_clk;
    initial begin #1.3; forever #3.75 dfi_clk=~dfi_clk; end
    reg usr_rst_n=0, dfi_rst_n=0, ddr_ready=0;
    reg [127:0] hdata=0;
    reg hvalid=0, hlast=0, cready=0;
    wire hready, cvalid, clast;
    wire [127:0] cdata;
    wire [15:0] ckeep, cuser;
    wire ddr_ok_u, bridge_u, idle_u, busy_u, fault_u, h_accepted, r_accepted;
    wire [3:0] err_u;
    wire soft_reset;
    reg wr_pulse=0;
    reg [31:0] wr_data=0;
    wire [31:0] status;
    wire ep_fault;
    wire [3:0] ep_error;
    kv_app_status #(.RESET_CYCLES(8'd8)) u_status (
        .clk(usr_clk), .rst_n(usr_rst_n), .wr_pulse(wr_pulse),
        .wr_addr(8'hA8), .wr_data(wr_data), .wr_strb(4'hF),
        .rd_addr(8'hA4), .rd_data(status), .ddr_ready(ddr_ok_u),
        .bridge_ready(bridge_u), .endpoint_idle(idle_u),
        .engine_busy(busy_u), .endpoint_fault(fault_u),
        .endpoint_error(err_u), .h2c_accepted(h_accepted),
        .response_accepted(r_accepted), .soft_reset_active(soft_reset));
    v2_endpoint_cdc #(.MAX_T(8)) u_cdc (
        .usr_clk(usr_clk), .usr_rst_n(usr_rst_n), .soft_reset(soft_reset),
        .usr_ddr_ready(ddr_ok_u), .usr_bridge_ready(bridge_u),
        .usr_endpoint_idle(idle_u), .usr_engine_busy(busy_u),
        .usr_fault(fault_u), .usr_error_code(err_u),
        .usr_h2c_accepted(h_accepted), .usr_response_accepted(r_accepted),
        .dfi_clk(dfi_clk), .dfi_rst_n(dfi_rst_n), .ddr_ready(ddr_ready),
        .m0_axis_h2c_tdata(hdata), .m0_axis_h2c_tkeep(16'hffff),
        .m0_axis_h2c_tuser(16'd0), .m0_axis_h2c_tlast(hlast),
        .m0_axis_h2c_tvalid(hvalid), .m0_axis_h2c_tready(hready),
        .s0_axis_c2h_tdata(cdata), .s0_axis_c2h_tkeep(ckeep),
        .s0_axis_c2h_tuser(cuser), .s0_axis_c2h_tlast(clast),
        .s0_axis_c2h_tvalid(cvalid), .s0_axis_c2h_tready(cready),
        .fault(ep_fault), .error_code(ep_error),
        .m_axi_awready(1'b0), .m_axi_arready(1'b0), .m_axi_wready(1'b0),
        .m_axi_bid(4'd0), .m_axi_rid(4'd0), .m_axi_bresp(2'd0), .m_axi_rresp(2'd0),
        .m_axi_bvalid(1'b0), .m_axi_rvalid(1'b0),
        .m_axi_rdata(128'd0), .m_axi_rlast(1'b0));
    task send;
        input [127:0] data;
        input last;
        begin
            @(negedge usr_clk); hdata=data; hlast=last; hvalid=1;
            @(posedge usr_clk);
            while(!hready) @(posedge usr_clk);
            @(negedge usr_clk); hvalid=0;
        end
    endtask
    task reset_frame;
        begin
            send(128'h00000000000000ff00010002584d564b,0);
            send(128'h00000000bd168fc50000000011223344,1);
        end
    endtask
    task wait_ready;
        integer n;
        begin
            n=0;
            while (!status[4] && n<100) begin @(negedge usr_clk); n=n+1; end
            if (!status[4]) $fatal(1,"READY did not return: %h",status);
        end
    endtask
    task command_reset;
        begin
            @(negedge usr_clk); wr_data=32'd1; wr_pulse=1;
            @(negedge usr_clk); wr_pulse=0;
            if(!soft_reset) $fatal(1,"SOFT_RESET did not assert");
        end
    endtask
    integer count=0;
    initial begin
        repeat(8) @(negedge usr_clk);
        usr_rst_n=1; dfi_rst_n=1; ddr_ready=1;
        wait_ready();
        reset_frame();
        wait(cvalid); // leave old ACK in C2H FIFO
        command_reset();
        repeat(12) @(negedge usr_clk);
        if(cvalid) $fatal(1,"stale ACK survived SOFT_RESET");
        wait_ready();
        reset_frame();
        @(negedge usr_clk); cready=1;
        while(count<2) begin
            @(posedge usr_clk);
            if(cvalid && cready) begin
                if(count==0 && (cdata!==128'h00000000000000ff00010002584d564b || clast))
                    $fatal(1,"bad ACK header0");
                if(count==1 && (cdata!==128'h00000000bd168fc50000000011223344 || !clast))
                    $fatal(1,"bad ACK header1/seq");
                count=count+1;
            end
        end
        @(negedge usr_clk); cready=0;
        if(status!==32'h11) $fatal(1,"DONE/READY status wrong: %h",status);
        repeat(20) @(negedge usr_clk);
        if(cvalid) $fatal(1,"duplicate ACK");
        // A malformed CRC leaves the endpoint faulted; BAR reset must rearm it.
        send(128'h00000000000000ff00010002584d564b,0);
        send(128'h00000000bd168fc40000000011223344,1);
        wait(fault_u);
        repeat(3) @(negedge usr_clk);
        if(!status[5] || status[4] || cvalid) $fatal(1,"bad CRC status=%h cvalid=%b",status,cvalid);
        command_reset();
        wait_ready();
        reset_frame();
        @(negedge usr_clk); cready=1;
        count=0;
        while(count<2) begin
            @(posedge usr_clk);
            if(cvalid && cready) begin
                if(count==0 && (cdata!==128'h00000000000000ff00010002584d564b || clast))
                    $fatal(1,"bad post-fault ACK header0");
                if(count==1 && (cdata!==128'h00000000bd168fc50000000011223344 || !clast))
                    $fatal(1,"bad post-fault ACK header1");
                count=count+1;
            end
        end
        $display("planb_soft_reset_cdc: PASS");
        $finish;
    end
    initial begin #100000; $fatal(1,"watchdog status=%h",status); end
endmodule

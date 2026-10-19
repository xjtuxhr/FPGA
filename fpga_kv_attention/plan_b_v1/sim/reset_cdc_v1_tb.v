`timescale 1ns/1ps
// RESET ACK: exact contract bytes/CRC/SEQ, exactly two beats, one TLAST.
// Two unrelated clocks, READY stalls, source gaps, DDR gate, either-domain reset.
module reset_cdc_tb;
    reg usr_clk=0, dfi_clk=0;
    parameter USR_HALF=4, DFI_HALF=3.75;
    always #(USR_HALF) usr_clk=~usr_clk;
    initial begin #1.3; forever #(DFI_HALF) dfi_clk=~dfi_clk; end
    reg usr_rst_n=0, dfi_rst_n=0, ddr_ready=0;
    reg [127:0] hdata=0;
    reg [15:0] hkeep=16'hffff;
    reg hvalid=0, hlast=0, cready=0;
    wire hready, cvalid, clast, fault, awvalid, arvalid, wvalid;
    wire [127:0] cdata;
    wire [15:0] ckeep, cuser;
    wire [3:0] error_code;
    v2_endpoint_cdc #(.MAX_T(8)) dut (
        .usr_clk(usr_clk), .usr_rst_n(usr_rst_n), .soft_reset(1'b0),
        .usr_accept_new(1'b1),
        .usr_quiesce_req(1'b0), .usr_quiesce_seen(),
        .dfi_clk(dfi_clk), .dfi_rst_n(dfi_rst_n), .ddr_ready(ddr_ready),
        .m0_axis_h2c_tdata(hdata), .m0_axis_h2c_tkeep(hkeep),
        .m0_axis_h2c_tuser(16'd0), .m0_axis_h2c_tvalid(hvalid),
        .m0_axis_h2c_tlast(hlast), .m0_axis_h2c_tready(hready),
        .s0_axis_c2h_tdata(cdata), .s0_axis_c2h_tkeep(ckeep),
        .s0_axis_c2h_tuser(cuser), .s0_axis_c2h_tvalid(cvalid),
        .s0_axis_c2h_tlast(clast), .s0_axis_c2h_tready(cready),
        .fault(fault), .error_code(error_code),
        .m_axi_awvalid(awvalid), .m_axi_arvalid(arvalid), .m_axi_wvalid(wvalid),
        .m_axi_awready(1'b0), .m_axi_arready(1'b0), .m_axi_wready(1'b0),
        .m_axi_bid(4'd0), .m_axi_rid(4'd0), .m_axi_bresp(2'd0), .m_axi_rresp(2'd0),
        .m_axi_bvalid(1'b0), .m_axi_rvalid(1'b0), .m_axi_rdata(128'd0), .m_axi_rlast(1'b0));
    integer cycle=0, ci=0, checked=0;
    reg stall=0, held_last;
    reg [127:0] held_data;
    always @(posedge usr_clk) begin
        cycle<=cycle+1;
        if(!usr_rst_n || !dfi_rst_n) stall<=0;
        else begin
            if(stall && (!cvalid || cdata !== held_data || clast !== held_last))
                $fatal(1,"case %0d changed C2H during stall",ci);
            stall<=cvalid && !cready;
            held_data<=cdata; held_last<=clast;
            if(cvalid && (ckeep!==16'hffff || cuser!==0)) $fatal(1,"sidebands");
        end
    end
    always @(posedge dfi_clk)
        if(dfi_rst_n && (awvalid || arvalid || wvalid)) $fatal(1,"RESET/TEST touched AXI");
    reg [127:0] vec[0:1314], req[0:123], exp[0:73];
    integer idx,nc,stage,err,sideband,gap,nr,ns,i,j,b;
    task send;
        input [127:0] data;
        input last;
        input [15:0] keep;
        begin
            @(negedge usr_clk); hdata=data; hlast=last; hkeep=keep; hvalid=1;
            @(posedge usr_clk);
            while(!hready) @(posedge usr_clk);
            @(negedge usr_clk); hvalid=0;
        end
    endtask
    task quiet;
        input integer n;
        begin
            repeat(n) begin
                @(negedge usr_clk);
                if(cvalid) begin
                    cready=1;
                    repeat(6) begin
                        @(posedge usr_clk);
                        if(cvalid) $display("unexpected ACK trace: %h last=%0d",cdata,clast);
                    end
                    $fatal(1,"case %0d unsolicited C2H during quiet/DDR gate",ci);
                end
            end
        end
    endtask
    initial begin
        $readmemh("golden/reset_cdc.hex",vec); idx=1; nc=vec[0];
        repeat(8) @(negedge usr_clk);
        usr_rst_n=1; dfi_rst_n=1; ddr_ready=1;
        quiet(16);
        for(ci=0;ci<nc;ci=ci+1) begin
            stage=vec[idx]; err=vec[idx+1]; sideband=vec[idx+2]; gap=vec[idx+3];
            nr=vec[idx+4]; ns=vec[idx+5]; idx=idx+6;
            for(i=0;i<nr;i=i+1) begin req[i]=vec[idx]; idx=idx+1; end
            for(i=0;i<ns;i=i+1) begin exp[i]=vec[idx]; idx=idx+1; end
            cready=0;
            if(stage==1) begin
                // Initial calibration gate, with the bridge session not yet
                // having observed READY. Later readiness loss is a full reset.
                dfi_rst_n=0; ddr_ready=0;
                repeat(8) @(negedge usr_clk);
                dfi_rst_n=1;
                quiet(16);
            end
            // Before either-domain reset, leave this same valid ACK unread.
            if(stage==2 || stage==3) begin
                for(i=0;i<nr;i=i+1) send(req[i],i==nr-1,16'hffff);
                wait(cvalid);
                @(negedge usr_clk);
                if(stage==2) usr_rst_n=0; else dfi_rst_n=0;
                repeat(8) @(negedge usr_clk);
                if(stage==2) usr_rst_n=1; else dfi_rst_n=1;
                quiet(40);
            end
            for(i=0;i<nr;i=i+1) begin
                if(gap && i) repeat(gap) @(negedge usr_clk);
                send(req[i],stage==4 ? i%2==1 : i==nr-1,(sideband==1 && i==1)?16'h7fff:16'hffff);
            end
            if(stage==1) begin
                quiet(100); ddr_ready=1;
            end
            if(err) begin
                quiet(100);
                if(!fault || error_code!==err) $fatal(1,"case %0d error %0d want %0d",ci,error_code,err);
            end else begin
                wait(cvalid);
                repeat(7) @(negedge usr_clk);
                b=0;
                while(b<ns) begin
                    @(negedge usr_clk); cready=(cycle%5!=0 && cycle%7!=2);
                    @(posedge usr_clk);
                    if(cvalid && cready) begin
                        if(cdata!==exp[b] || clast!==(stage==4 ? b%2==1 : b==ns-1))
                            $fatal(1,"case %0d beat %0d got %h last=%0d want %h",ci,b,cdata,clast,exp[b]);
                        b=b+1; checked=checked+1;
                    end
                end
                @(negedge usr_clk); cready=1;
                quiet(100);
                if(fault) $fatal(1,"case %0d unexpected error %0d",ci,error_code);
            end
            $display("case %0d PASS stage=%0d error=%0d",ci,stage,err);
        end
        $display("reset_cdc: ALL %0d cases PASSED (%0d response beats)",nc,checked);
        $finish;
    end
    initial begin #2000000; $fatal(1,"RESET CDC watchdog case %0d",ci); end
endmodule

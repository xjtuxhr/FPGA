`timescale 1ns/1ps
// ============================================================================
// v2_endpoint_cdc.v —— v2_endpoint 跨时钟封装
//
//   [usr_clk] SGDMA AXIS  <--异步FIFO-->  [dfi_clk] v2_endpoint(step3) --AXI4--> ui_ddr
//
// H2C（host->FPGA）与 C2H（FPGA->host）两条 AXIS 流分别用 async_fifo 跨域；
// v2_endpoint 内部（attention_engine + kv_store_axi + axi4_master）整体跑 dfi_clk，
// AXI4 直接连 ui_ddr。ddr_ready 在 cal_done 前背压并复位引擎。
// ============================================================================
module v2_endpoint_cdc #(
    parameter MAX_T  = 256,
    parameter LAYERS = 30,
    parameter ADDR_W = 28,
    parameter ID_W   = 4,
    parameter SCORE_SHIFT = 0
)(
    // ---- user_clk 侧（接 SGDMA）----
    input  wire usr_clk,
    input  wire usr_rst_n,
    input  wire [127:0] m0_axis_h2c_tdata,
    input  wire [15:0]  m0_axis_h2c_tkeep,
    input  wire [15:0]  m0_axis_h2c_tuser,
    input  wire         m0_axis_h2c_tlast,
    input  wire         m0_axis_h2c_tvalid,
    output wire         m0_axis_h2c_tready,
    output wire [127:0] s0_axis_c2h_tdata,
    output wire [15:0]  s0_axis_c2h_tkeep,
    output wire [15:0]  s0_axis_c2h_tuser,
    output wire         s0_axis_c2h_tlast,
    output wire         s0_axis_c2h_tvalid,
    input  wire         s0_axis_c2h_tready,

    // ---- dfi_clk 侧（接 ui_ddr / 顶层）----
    input  wire dfi_clk,
    input  wire dfi_rst_n,      // 建议接 ddr_init_cal_done（DDR 就绪前复位引擎）
    input  wire ddr_ready,      // pll_locked & ddr_init_cal_done
    output wire fault,
    output wire [3:0] error_code,

    // ---- AXI4 master（接 ui_ddr 的 axi_*）----
    output wire [ID_W-1:0]   m_axi_awid, m_axi_arid,
    output wire [ADDR_W-1:0] m_axi_awaddr, m_axi_araddr,
    output wire [7:0]  m_axi_awlen, m_axi_arlen,
    output wire [2:0]  m_axi_awsize, m_axi_arsize,
    output wire [1:0]  m_axi_awburst, m_axi_arburst,
    output wire m_axi_awvalid, m_axi_arvalid,
    input  wire m_axi_awready, m_axi_arready,
    output wire [127:0] m_axi_wdata,
    output wire [15:0]  m_axi_wstrb,
    output wire m_axi_wlast, m_axi_wvalid,
    input  wire m_axi_wready,
    input  wire [ID_W-1:0] m_axi_bid, m_axi_rid,
    input  wire [1:0]  m_axi_bresp, m_axi_rresp,
    input  wire m_axi_bvalid, m_axi_rvalid,
    output wire m_axi_bready, m_axi_rready,
    input  wire [127:0] m_axi_rdata,
    input  wire m_axi_rlast
);
    // Reset both pointer domains together. A PCIe/PERST reset must not leave
    // the DDR-side pointers or parser alive with a stale queued ACK.
    // Assertion is asynchronous; release is synchronized in each domain.
    wire board_arst_n = usr_rst_n && dfi_rst_n;
    reg ddr_seen_ready;
    always @(posedge dfi_clk or negedge board_arst_n)
        if(!board_arst_n) ddr_seen_ready <= 0;
        else if(ddr_ready) ddr_seen_ready <= 1;
    // Initial calibration may queue H2C in the FIFO. Once DDR was ready,
    // readiness loss invalidates both FIFOs, parser and all cache history.
    wire bridge_arst_n = board_arst_n && (ddr_ready || !ddr_seen_ready);
    (* ASYNC_REG = "TRUE" *) reg [1:0] usr_release, dfi_release;
    (* ASYNC_REG = "TRUE" *) reg [1:0] dfi_up_usr, usr_up_dfi;
    always @(posedge usr_clk or negedge bridge_arst_n)
        if(!bridge_arst_n) begin usr_release<=0; dfi_up_usr<=0; end
        else begin usr_release<={usr_release[0],1'b1}; dfi_up_usr<={dfi_up_usr[0],dfi_release[1]}; end
    always @(posedge dfi_clk or negedge bridge_arst_n)
        if(!bridge_arst_n) begin dfi_release<=0; usr_up_dfi<=0; end
        else begin dfi_release<={dfi_release[0],1'b1}; usr_up_dfi<={usr_up_dfi[0],usr_release[1]}; end
    wire usr_up = usr_release[1] && dfi_up_usr[1];
    wire dfi_up = dfi_release[1] && usr_up_dfi[1];
    // ---- H2C 异步 FIFO（usr_clk -> dfi_clk），打包 tdata+tlast+tkeep ----
    localparam H2C_W = 128 + 1 + 16;   // 145
    wire [H2C_W-1:0] h2c_wdata = {m0_axis_h2c_tdata, m0_axis_h2c_tlast, m0_axis_h2c_tkeep};
    wire [H2C_W-1:0] h2c_rdata;
    wire h2c_rvalid, h2c_rready;
    wire h2c_wready;
    assign m0_axis_h2c_tready = usr_up && h2c_wready;
    async_fifo #(.DATA_W(H2C_W), .DEPTH(256), .ADDR_W(8)) u_h2c_fifo (
        .w_clk(usr_clk), .w_rst_n(usr_release[1]),
        .w_valid(m0_axis_h2c_tvalid && usr_up), .w_data(h2c_wdata), .w_ready(h2c_wready),
        .r_clk(dfi_clk), .r_rst_n(dfi_release[1]),
        .r_valid(h2c_rvalid), .r_data(h2c_rdata), .r_ready(h2c_rready));

    // ---- C2H 异步 FIFO（dfi_clk -> usr_clk），打包 tdata+tlast ----
    localparam C2H_W = 128 + 1;   // 129
    wire [C2H_W-1:0] c2h_wdata;
    wire c2h_wvalid, c2h_wready;
    wire [C2H_W-1:0] c2h_rdata;
    wire c2h_rvalid;
    async_fifo #(.DATA_W(C2H_W), .DEPTH(256), .ADDR_W(8)) u_c2h_fifo (
        .w_clk(dfi_clk), .w_rst_n(dfi_release[1]),
        .w_valid(c2h_wvalid), .w_data(c2h_wdata), .w_ready(c2h_wready),
        .r_clk(usr_clk), .r_rst_n(usr_release[1]),
        .r_valid(c2h_rvalid), .r_data(c2h_rdata), .r_ready(s0_axis_c2h_tready && usr_up));

    // C2H 输出（usr_clk 侧）：tkeep/tuser 固定，tdata/tlast 来自 FIFO
    assign s0_axis_c2h_tdata  = c2h_rdata[128:1];
    assign s0_axis_c2h_tlast  = c2h_rdata[0];
    assign s0_axis_c2h_tkeep  = 16'hFFFF;
    assign s0_axis_c2h_tuser  = 16'd0;
    assign s0_axis_c2h_tvalid = c2h_rvalid && usr_up;

    // ---- v2_endpoint（dfi_clk 侧）----
    wire [127:0] ep_c2h_tdata;
    wire         ep_c2h_tlast, ep_c2h_tvalid, ep_c2h_tready;
    assign c2h_wdata = {ep_c2h_tdata, ep_c2h_tlast};
    assign c2h_wvalid = ep_c2h_tvalid;
    assign ep_c2h_tready = c2h_wready;

    v2_endpoint #(.MAX_T(MAX_T), .LAYERS(LAYERS), .ADDR_W(ADDR_W), .ID_W(ID_W), .DDR_GATE(1), .SCORE_SHIFT(SCORE_SHIFT)) u_ep (
        .clk(dfi_clk), .rst_n(dfi_release[1]), .ddr_ready(ddr_ready && dfi_up),
        .m0_axis_h2c_tdata(h2c_rdata[144:17]), .m0_axis_h2c_tkeep(h2c_rdata[15:0]),
        .m0_axis_h2c_tuser(16'd0), .m0_axis_h2c_tlast(h2c_rdata[16]),
        .m0_axis_h2c_tvalid(h2c_rvalid), .m0_axis_h2c_tready(h2c_rready),
        .s0_axis_c2h_tdata(ep_c2h_tdata), .s0_axis_c2h_tkeep(),
        .s0_axis_c2h_tuser(), .s0_axis_c2h_tlast(ep_c2h_tlast),
        .s0_axis_c2h_tvalid(ep_c2h_tvalid), .s0_axis_c2h_tready(ep_c2h_tready),
        .fault(fault), .error_code(error_code),
        .m_axi_awid(m_axi_awid), .m_axi_arid(m_axi_arid),
        .m_axi_awaddr(m_axi_awaddr), .m_axi_araddr(m_axi_araddr),
        .m_axi_awlen(m_axi_awlen), .m_axi_arlen(m_axi_arlen),
        .m_axi_awsize(m_axi_awsize), .m_axi_arsize(m_axi_arsize),
        .m_axi_awburst(m_axi_awburst), .m_axi_arburst(m_axi_arburst),
        .m_axi_awvalid(m_axi_awvalid), .m_axi_arvalid(m_axi_arvalid),
        .m_axi_awready(m_axi_awready), .m_axi_arready(m_axi_arready),
        .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(m_axi_wstrb),
        .m_axi_wlast(m_axi_wlast), .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_bid(m_axi_bid), .m_axi_bresp(m_axi_bresp),
        .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(m_axi_bready),
        .m_axi_rid(m_axi_rid), .m_axi_rdata(m_axi_rdata), .m_axi_rresp(m_axi_rresp),
        .m_axi_rlast(m_axi_rlast), .m_axi_rvalid(m_axi_rvalid), .m_axi_rready(m_axi_rready));

endmodule

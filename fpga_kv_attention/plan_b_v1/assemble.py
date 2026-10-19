"""Assemble PC2 Plan B v1 into a fresh B64S3+DDR TD project; never program hardware."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "plan_b_status" / "assemble.py"


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one anchor; found {count}")
    return text.replace(old, new, 1)


def change(path: Path, fn) -> None:
    src = path.read_text(encoding="utf-8", errors="replace")
    dst = fn(src)
    path.write_bytes(dst.replace("\n", "\r\n").encode("utf-8"))


def modify_top(text: str) -> str:
    begin = "    // Candidate BAR0 status/control interface, synchronous to user_clk."
    end = "        .soft_reset_active(app_soft_reset));"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError("candidate status block missing or duplicated")
    start = text.index(begin)
    stop = text.index(end, start) + len(end)
    replacement = """    // PC2 Plan B v1: application status, version marker and safe reset gate.
    wire app_soft_reset, app_soft_reset_req, app_session_abort_req;
    wire app_guard_block, app_fault_mask, app_accept_new;
    wire app_usr_ddr_ready, app_usr_bridge_ready, app_usr_endpoint_idle;
    wire app_usr_engine_busy, app_usr_axi_quiescent, app_usr_quiesce_seen, app_usr_fault;
    wire app_usr_request_start, app_usr_frame_active, app_usr_response_ready;
    wire app_usr_h2c_accepted, app_usr_response_accepted;
    wire [3:0] app_usr_error_code;
    wire [31:0] planb_rdata, planb_status;
    wire planb_rsel;
    reg ddr_was_ready, ddr_lost;
    always @(posedge user_clk or negedge user_rst_n) begin
        if (!user_rst_n) begin ddr_was_ready <= 0; ddr_lost <= 0; end
        else if (app_soft_reset_req) begin ddr_was_ready <= 0; ddr_lost <= 0; end
        else begin
            if (app_usr_ddr_ready) ddr_was_ready <= 1;
            if (ddr_was_ready && !app_usr_ddr_ready) ddr_lost <= 1;
        end
    end
    function [2:0] planb_map_err;
        input [3:0] code;
        begin
            case (code)
                4'd0: planb_map_err = 3'd0;
                4'd1, 4'd2, 4'd3: planb_map_err = 3'd3;
                4'd4: planb_map_err = 3'd1;
                4'd5: planb_map_err = 3'd2;
                4'd6: planb_map_err = 3'd4;
                default: planb_map_err = 3'd5;
            endcase
        end
    endfunction
    wire app_fault_in = (app_usr_fault || ddr_lost) && !app_fault_mask;
    wire [2:0] app_err_in = ddr_lost ? 3'd4 : planb_map_err(app_usr_error_code);
    wire app_ready_raw = app_usr_ddr_ready && app_usr_bridge_ready &&
                         app_usr_endpoint_idle && !app_usr_engine_busy &&
                         !app_usr_frame_active && !app_guard_block &&
                         !app_fault_in;
    wire app_busy_raw = app_usr_engine_busy || !app_usr_endpoint_idle ||
                        app_usr_frame_active || app_guard_block;
    // Quiescence is valid only after the DDR clock domain has observed the
    // block request. A partial H2C frame may be discarded by the reset.
    wire app_axi_safe = (app_usr_quiesce_seen && app_usr_axi_quiescent) ||
                        (!ddr_was_ready && !app_usr_bridge_ready);
    planb_status_ctrl u_planb_status_ctrl (
        .clk(user_clk), .rst_n(user_rst_n),
        .axil_awaddr(m_axil_awaddr), .axil_awvalid(m_axil_awvalid),
        .axil_wvalid(m_axil_wvalid), .axil_wdata(m_axil_wdata),
        .axil_araddr(m_axil_araddr), .axil_arvalid(m_axil_arvalid),
        .start_i(app_usr_request_start), .done_i(app_usr_response_ready),
        .ready_i(app_ready_raw), .busy_i(app_busy_raw),
        .fault_i(app_fault_in), .err_i(app_err_in),
        .rdata_o(planb_rdata), .rsel_o(planb_rsel),
        .soft_reset_o(app_soft_reset_req),
        .session_abort_o(app_session_abort_req), .status_o(planb_status));
    assign app_accept_new = planb_status[4];
    planb_reset_guard u_planb_reset_guard (
        .clk(user_clk), .rst_n(user_rst_n),
        .soft_reset_req(app_soft_reset_req),
        .session_abort_req(app_session_abort_req),
        .axi_quiescent(app_axi_safe),
        .bridge_ready(app_usr_bridge_ready || !ddr_was_ready),
        .reset_active(app_soft_reset), .block_new(app_guard_block),
        .mask_endpoint_fault(app_fault_mask));"""
    text = text[:start] + replacement + text[stop:]
    text = once(text,
        "                             (m_axil_araddr[7:0] <= 8'hA0 ||\n"
        "                              app_status_rd_hit);",
        "                             (m_axil_araddr[7:0] <= 8'hA0);",
        "restore video read range")
    text = once(text,
        "            8'hA4:               vid_reg_rdata_d1 <= app_status_rdata;\n"
        "            8'hA8:               vid_reg_rdata_d1 <= 32'd0;\n",
        "", "remove candidate video cases")
    text = once(text,
        "    assign m_axil_rdata = vid_rd_sel_d1 ? vid_reg_rdata_d1 : app_axil_rdata;",
        "    assign m_axil_rdata = planb_rsel ? planb_rdata :\n"
        "                            vid_rd_sel_d1 ? vid_reg_rdata_d1 : app_axil_rdata;",
        "Plan B read priority")
    text = once(text,
        "    .app_usr_engine_busy         (app_usr_engine_busy),",
        "    .app_usr_engine_busy         (app_usr_engine_busy),\n"
        "    .app_usr_axi_quiescent       (app_usr_axi_quiescent),\n"
        "    .app_usr_quiesce_seen        (app_usr_quiesce_seen),\n"
        "    .app_usr_request_start       (app_usr_request_start),\n"
        "    .app_usr_frame_active        (app_usr_frame_active),\n"
        "    .app_usr_response_ready      (app_usr_response_ready),\n"
        "    .app_accept_new             (app_accept_new),\n"
        "    .app_quiesce_req            (app_guard_block),",
        "top SGDMA status ports")
    return text


def modify_app(text: str) -> str:
    text = once(text,
        "    input   wire            app_soft_reset,",
        "    input   wire            app_soft_reset,\n"
        "    input   wire            app_accept_new,\n"
        "    input   wire            app_quiesce_req,",
        "app accept port")
    text = once(text,
        "    output  wire            app_usr_engine_busy,",
        "    output  wire            app_usr_engine_busy,\n"
        "    output  wire            app_usr_axi_quiescent,\n"
        "    output  wire            app_usr_quiesce_seen,\n"
        "    output  wire            app_usr_request_start,\n"
        "    output  wire            app_usr_frame_active,\n"
        "    output  wire            app_usr_response_ready,",
        "app extra status ports")
    text = once(text,
        "        .soft_reset                 (app_soft_reset),",
        "        .soft_reset                 (app_soft_reset),\n"
        "        .usr_accept_new             (app_accept_new),\n"
        "        .usr_quiesce_req            (app_quiesce_req),\n"
        "        .usr_quiesce_seen           (app_usr_quiesce_seen),",
        "CDC accept port")
    text = once(text,
        "        .usr_engine_busy            (app_usr_engine_busy),",
        "        .usr_engine_busy            (app_usr_engine_busy),\n"
        "        .usr_axi_quiescent          (app_usr_axi_quiescent),\n"
        "        .usr_request_start          (app_usr_request_start),\n"
        "        .usr_frame_active           (app_usr_frame_active),\n"
        "        .usr_response_ready         (app_usr_response_ready),",
        "CDC status ports")
    return text


def modify_project(text: str) -> str:
    pattern = (r'            <File Path="(?:\.\./\.\./)?uisrc/01_rtl/kv_app_status\.v">\n'
               r'.*?            </File>\n')
    text, count = re.subn(pattern, "", text, count=1, flags=re.S)
    if count != 1:
        raise ValueError("old status TD source entry missing")
    prefix = "../../" if '<File Path="../../uisrc/01_rtl/v2_endpoint.v">' in text else ""
    anchor = f'            <File Path="{prefix}uisrc/01_rtl/v2_endpoint.v">'
    entries = ""
    for order, name in ((205, "planb_status_ctrl.v"), (206, "planb_reset_guard.v")):
        entries += (f'            <File Path="{prefix}uisrc/01_rtl/{name}">\n'
                    '                <FileInfo>\n'
                    '                    <Attr Name="UsedInSyn" Val="true"/>\n'
                    '                    <Attr Name="UsedInP&R" Val="true"/>\n'
                    '                    <Attr Name="BelongTo" Val="design_1"/>\n'
                    f'                    <Attr Name="CompileOrder" Val="{order}"/>\n'
                    '                </FileInfo>\n'
                    '            </File>\n')
    return once(text, anchor, entries + anchor, "new status TD sources")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    cmd = [sys.executable, str(OLD), "--out", str(args.out)]
    if args.base:
        cmd.extend(["--base", str(args.base)])
    subprocess.run(cmd, check=True)
    root = args.out.resolve()
    for name in ("planb_status_ctrl.v", "planb_reset_guard.v", "v2_endpoint_cdc.v", "v2_endpoint.v"):
        shutil.copyfile(HERE / "rtl" / name, root / "uisrc" / "01_rtl" / name)
    change(root / "uisrc/01_rtl/imx415_pcie_top.v", modify_top)
    change(root / "uisrc/03_ip/sgdma/sgdma_app/src/sgdma_app.v", modify_app)
    for rel in ("attention_ddr.al", "attention_ddr.prj", "build/syn_1/attention_ddr.prj"):
        change(root / rel, modify_project)
    print(f"PASS: PC2 Plan B v1 TD project assembled at {root}")


if __name__ == "__main__":
    main()

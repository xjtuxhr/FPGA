"""Build a separate reviewable TD project from frozen B64S3 plus Plan B RTL.

This script never runs TD and never programs the board. BAR map is a candidate
until PC2/B agree on SESSION_ABORT and recovery semantics.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent / "functional_b64s3" / "assemble.py"
BASE_DEFAULT = Path(r"E:\KVmix\fpga_ddr_diag_20261014")


def replace_one(text: str, old: str, new: str, name: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{name}: expected one anchor, found {count}: {old[:80]!r}")
    return text.replace(old, new, 1)


def write_modified(path: Path, modify) -> None:
    original = path.read_text(encoding="utf-8", errors="replace")
    updated = modify(original)
    path.write_bytes(updated.replace("\n", "\r\n").encode("utf-8"))


def modify_app(text: str) -> str:
    text = replace_one(text, "    input   wire            dfi_clk,",
        "    input   wire            app_soft_reset,\n"
        "    output  wire            app_usr_ddr_ready,\n"
        "    output  wire            app_usr_bridge_ready,\n"
        "    output  wire            app_usr_endpoint_idle,\n"
        "    output  wire            app_usr_engine_busy,\n"
        "    output  wire            app_usr_fault,\n"
        "    output  wire    [3:0]   app_usr_error_code,\n"
        "    output  wire            app_usr_h2c_accepted,\n"
        "    output  wire            app_usr_response_accepted,\n"
        "    input   wire            dfi_clk,", "sgdma app ports")
    text = replace_one(text, "        .usr_rst_n                  (usr_rst_n),\n        .m0_axis_h2c_tdata",
        "        .usr_rst_n                  (usr_rst_n),\n"
        "        .soft_reset                 (app_soft_reset),\n"
        "        .usr_ddr_ready              (app_usr_ddr_ready),\n"
        "        .usr_bridge_ready           (app_usr_bridge_ready),\n"
        "        .usr_endpoint_idle          (app_usr_endpoint_idle),\n"
        "        .usr_engine_busy            (app_usr_engine_busy),\n"
        "        .usr_fault                  (app_usr_fault),\n"
        "        .usr_error_code             (app_usr_error_code),\n"
        "        .usr_h2c_accepted           (app_usr_h2c_accepted),\n"
        "        .usr_response_accepted      (app_usr_response_accepted),\n"
        "        .m0_axis_h2c_tdata", "sgdma endpoint instance")
    return text


def modify_top(text: str) -> str:
    text = replace_one(text, "    wire wr_pulse = wr_hit && !wr_hit_d1;  // rising edge of wr_hit",
        "    wire wr_pulse = wr_hit && !wr_hit_d1;  // rising edge of wr_hit\n"
        "    // Candidate BAR0 status/control interface, synchronous to user_clk.\n"
        "    wire app_soft_reset;\n"
        "    wire app_usr_ddr_ready, app_usr_bridge_ready, app_usr_endpoint_idle;\n"
        "    wire app_usr_engine_busy, app_usr_fault;\n"
        "    wire [3:0] app_usr_error_code;\n"
        "    wire app_usr_h2c_accepted, app_usr_response_accepted;\n"
        "    wire [31:0] app_status_rdata;\n"
        "    kv_app_status u_kv_app_status (\n"
        "        .clk(user_clk), .rst_n(user_rst_n),\n"
        "        .wr_pulse(wr_pulse && m_axil_awaddr[31:8] == 24'd0),\n"
        "        .wr_addr(m_axil_awaddr[7:0]), .wr_data(m_axil_wdata),\n"
        "        .wr_strb(m_axil_wstrb), .rd_addr(m_axil_araddr[7:0]),\n"
        "        .rd_data(app_status_rdata), .ddr_ready(app_usr_ddr_ready),\n"
        "        .bridge_ready(app_usr_bridge_ready),\n"
        "        .endpoint_idle(app_usr_endpoint_idle),\n"
        "        .engine_busy(app_usr_engine_busy), .endpoint_fault(app_usr_fault),\n"
        "        .endpoint_error(app_usr_error_code),\n"
        "        .h2c_accepted(app_usr_h2c_accepted),\n"
        "        .response_accepted(app_usr_response_accepted),\n"
        "        .soft_reset_active(app_soft_reset));", "top BAR write intercept")
    text = replace_one(text,
        "                             (m_axil_araddr[7:0] <= 8'hA0);",
        "                             ((m_axil_araddr[7:0] <= 8'hA0) ||\n"
        "                              ((m_axil_araddr[31:8] == 24'd0) &&\n"
        "                               (m_axil_araddr[7:0] == 8'hA4 ||\n"
        "                                m_axil_araddr[7:0] == 8'hA8)));",
        "top BAR read intercept")
    text = replace_one(text,
        "            default:              vid_reg_rdata_d1 <= 32'd0;",
        "            8'hA4:               vid_reg_rdata_d1 <= app_status_rdata;\n"
        "            8'hA8:               vid_reg_rdata_d1 <= 32'd0;\n"
        "            default:              vid_reg_rdata_d1 <= 32'd0;",
        "top BAR read data")
    text = replace_one(text,
        "    .dfi_clk                    (ddr_dfi_clk),",
        "    .app_soft_reset             (app_soft_reset),\n"
        "    .app_usr_ddr_ready           (app_usr_ddr_ready),\n"
        "    .app_usr_bridge_ready        (app_usr_bridge_ready),\n"
        "    .app_usr_endpoint_idle       (app_usr_endpoint_idle),\n"
        "    .app_usr_engine_busy         (app_usr_engine_busy),\n"
        "    .app_usr_fault               (app_usr_fault),\n"
        "    .app_usr_error_code          (app_usr_error_code),\n"
        "    .app_usr_h2c_accepted        (app_usr_h2c_accepted),\n"
        "    .app_usr_response_accepted   (app_usr_response_accepted),\n"
        "    .dfi_clk                    (ddr_dfi_clk),",
        "top sgdma instance")
    return text


def add_td_file(text: str) -> str:
    prefix = "../../" if '<File Path="../../uisrc/01_rtl/v2_endpoint.v">' in text else ""
    anchor = f'            <File Path="{prefix}uisrc/01_rtl/v2_endpoint.v">'
    entry = (f'            <File Path="{prefix}uisrc/01_rtl/kv_app_status.v">\n'
             '                <FileInfo>\n'
             '                    <Attr Name="UsedInSyn" Val="true"/>\n'
             '                    <Attr Name="UsedInP&R" Val="true"/>\n'
             '                    <Attr Name="BelongTo" Val="design_1"/>\n'
             '                    <Attr Name="CompileOrder" Val="205"/>\n'
             '                </FileInfo>\n'
             '            </File>\n')
    return replace_one(text, anchor, entry + anchor, "TD design file list")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE_DEFAULT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    subprocess.run([sys.executable, str(FROZEN), "--base", str(args.base),
                    "--out", str(args.out)], check=True)
    root = args.out.resolve()
    for name in ("kv_app_status.v", "v2_endpoint.v", "v2_endpoint_cdc.v"):
        shutil.copyfile(HERE / "rtl" / name, root / "uisrc" / "01_rtl" / name)
    write_modified(root / "uisrc/01_rtl/imx415_pcie_top.v", modify_top)
    write_modified(root / "uisrc/03_ip/sgdma/sgdma_app/src/sgdma_app.v", modify_app)
    for rel in ("attention_ddr.al", "attention_ddr.prj", "build/syn_1/attention_ddr.prj"):
        write_modified(root / rel, add_td_file)
    template = (HERE / "td" / "holdfix_candidate.tcl.in").read_text(encoding="utf-8")
    (root / "holdfix_candidate.tcl").write_text(
        template.replace("@BUILD_ROOT@", root.as_posix()), encoding="utf-8")
    print(f"PASS: candidate Plan B TD project assembled at {root}")


if __name__ == "__main__":
    main()

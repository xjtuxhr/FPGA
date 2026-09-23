<?xml version="1.0" encoding="UTF-8"?>
<Project Version="3" Minor="2" Path="F:/al_data/PH1A/AFH03_AFC03/00_for_starter/02_fpga_start">
    <Project_Created_Time></Project_Created_Time>
    <TD_Version>6.2.200067</TD_Version>
    <Name>fpga_prj</Name>
    <HardWare>
        <Family>PH1</Family>
        <Device>PH1A90SEG324</Device>
        <Speed>-2</Speed>
    </HardWare>
    <Source_Files>
        <Verilog>
            <File Path="uisrc/01_rtl/pll_test.v">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="1"/>
                </FileInfo>
            </File>
        </Verilog>
        <IP_FILE>
            <File Path="uisrc/03_ip/pll.ipc">
                <FileInfo>
                    <Attr Name="UsedInSyn" Val="true"/>
                    <Attr Name="UsedInP&R" Val="true"/>
                    <Attr Name="BelongTo" Val="design_1"/>
                    <Attr Name="CompileOrder" Val="2"/>
                </FileInfo>
            </File>
        </IP_FILE>
    </Source_Files>
    <FileSets>
        <FileSet Name="design_1" Type="DesignFiles">
        </FileSet>
        <FileSet Name="constraint_1" Type="ConstrainFiles">
        </FileSet>
    </FileSets>
    <TOP_MODULE>
        <LABEL>pll_test</LABEL>
        <MODULE>pll_test</MODULE>
        <CREATEINDEX>auto</CREATEINDEX>
    </TOP_MODULE>
    <Property>
        <SimProperty>
            <lib>E:/modelsim/modelsim/anlogic/PH1</lib>
        </SimProperty>
    </Property>
    <Device_Settings>
    </Device_Settings>
    <Configurations>
    </Configurations>
    <Runs>
        <Run Name="syn_1" Type="Synthesis" ConstraintSet="constraint_1" Description="" Active="true">
            <Strategy Name="Default_Synthesis_Strategy">
                <GateProperty>
                    <map_sim_model>on</map_sim_model>
                </GateProperty>
            </Strategy>
            <UserParams>
            </UserParams>
        </Run>
        <Run Name="phy_1" Type="PhysicalDesign" ConstraintSet="constraint_1" Description="" SynRun="syn_1" Active="true">
            <Strategy Name="Default_PhysicalDesign_Strategy">
            </Strategy>
            <UserParams>
            </UserParams>
        </Run>
    </Runs>
    <Project_Settings>
    </Project_Settings>
</Project>

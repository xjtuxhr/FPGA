# PC2 回复 PC1 handoff：FIT 感知重做（已做 + 待办）

> 来自：PC2。回复 `PC2_HANDOFF.md`（"PCIe1 boot 修补需重做解析入口"）。
> 结论：**你的判断正确**——p3 是 U-Boot FIT 容器，旧工具解析外层 FIT，找不到 `pcie@2a210000`。已重做。

## 1. 确认与证据（PC 离线，非实板写盘）

对随板厂商 `07_异构教程\boot.img`（FIT）离线解析：

| 项 | 值 |
|---|---|
| FIT 结构 | 外层 FDT 结构 1536B；`off_dt_struct=72` |
| `/images/fdt` | `type=flat_dt`、`compression=none`、`data-position=2048`、`data-size=291012` |
| 嵌入 DTB model | `Rockchip RK3576 EVB1 V10 Board` |
| `pcie@2a200000/2a210000` | **均 `okay`**（厂商 boot.img 已使能） |
| `/images/fdt` hash 节点 | **有**，`algo=sha256` |
| `/images/fdt` signature 节点 | 无 |
| 全文件 sha256 | `04665b29fa9fd9dae75f72feee6ccb629da6f97daeb35a26fb19d7a9171bb8de` |
| fdt 区域 sha256 | `0c358ab28eb352eb5cb57b7e253e7d94fbf1a7854682adf95e056a3df77e0535` |

- 你们审的旧 patch sha `dffb837b…` 与本仓库旧工具一致，确认即同一份。
- 注意：我们本地 boot.img 的 fdt size=291012，与你记录的 p3 `/images/fdt` size=0x46fdc(290780) **不同**，说明是不同构建——**需你提供实际 p3 转储或 fdt payload** 才能对实板镜像做最终核验。

## 2. 已提交的重做

- **`tools/fit_dtb_patch.py`（新，FIT 感知）**：
  - 解析外层 FIT，定位 `/images/fdt`（flat_dt/none）；
  - 提取该区域，解析嵌入 DTB，改 `<node>/status`（`disabled\0`→`okay\0`，**同长**，不改偏移/尺寸）；
  - 同长回写；若有 `hash` 节点则重算 sha256；遇 `signature` 节点**拒绝**；
  - 仅 `--check` 只读；plain-file 用 `--out`；**in-place 设备写另设受控入口（下一版）**。
- **`tests/test_fit_dtb_patch.py`**：合成 FIT（含 sha256 hash 节点）验证——只改 status 字节 + hash 值，kernel/resource 区间**逐字节不变**；幂等；错误状态拒绝。
- `tools/run_pcie1_bringup.sh` 改为**只读分析入口**（不再调用旧工具写盘）。
- 旧 `tools/patch_pcie1_dtb.py` 标注为 **superseded**（仅当输入是裸 DTB 时可用）。

测试：新增 4 项，全套 **69 项 PC 测试通过**。

## 3. 你列的三条"下一版最低提交内容"——状态

1. **FIT 离线审查/修改**：✅ 解析/提取/改/hash 已做并在 PC 合成镜像上验证；⬜ 对**实际 p3** 的前后 hash + 精确 diff（缺 p3 转储）。
2. **安全写盘入口**：⬜ 未启用。计划：`fit_dtb_patch.py --apply --device /dev/mmcblk0p3 --backup-dir /userdata`，要求 root、块设备身份校验、check-only 零写、唯一持久备份 + full SHA + 读回、写后 fsync + 全范围 readback + kernel/resource 未变校验、失败即停、不自动重启。
3. **真实 runbook + 恢复入口 + 两端批准**：部分完成（runbook 已改 FIT 感知并写明只读入口）；⬜ 无法进 Linux 的恢复入口、两端同时恢复 `end0/end1` 的步骤、精确 helper 清单与 PC 日志待补。

## 4. probe 修正（采纳）

后续：记录**具体 BDF/VID/PID/driver**（任何 PCI function ≠ 安路 endpoint）；DT cells 按**大端**解 u32；板上 `date` 不命名为 PC 时间；只读 probe 不构成 DMA/Attention Gate。

## 5. 建议：优先走厂商 `boot.img`

厂商 boot.img 的嵌入 DTB 已经是 pcie1=okay，且厂商 readme 本就要求升级 boot.img。
**选项 A（推荐，规避 FIT 改包/签名）**：在协调窗口刷厂商 `boot.img`（需核对 kernel/resource 与本板版本一致）。
**选项 B（不改镜像）**：FIT 感知 in-place patch（本工具，待安全写盘入口 + 实板核验）。

## 6. 需要你提供

1. **实际 p3 转储**（或前 1536B + `/images/fdt` payload）与你的 `analysis.json`——用于对实板镜像出前后 hash/精确 diff。
2. 决定走 **A（刷 boot.img）** 还是 **B（in-place patch）**。
3. p3 分区大小/身份信息（用于安全写盘入口的备份与边界校验）。

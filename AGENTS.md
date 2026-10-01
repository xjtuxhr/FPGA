# Project collaboration rules

Before any host, PCIe, FPGA or board-test work, read and follow:

1. `pcie_contract/COOPERATION.md` — agreed ownership, separate directories/branches, exclusive board-test windows, system-change approvals and evidence.
2. `pcie_contract/README.md` — versioned test contract and verified-vs-unverified boundaries.
3. `PLAN.md` and `docs/UNKNOWNS.md` — project scope and the single active UNKNOWN registry.

PC1 owns host/NPU/reference/scheduler; PC2 owns PCIe transport/endpoint. Both
SSH connections reach the same RK3576 and share its devices and filesystem.
Do not operate the board remotely by default. Use the Human-in-the-loop SOP:
one explicitly authorized hardware experiment, user-supplied complete output,
then analyze. Obtain the other operator's board-idle confirmation first.

Preserve unrelated dirty files. Do not stage all files or force-push main.
Do not overwrite another operator's directory/results, replace system runtime,
disable SGDMA interrupts, or run vendor setup/rebind/flash scripts as diagnostics.
These rules are not permission to push, send messages, or change system state.
Those actions still require user authorization.

Treat v2 as a fixed SOFTWARE TEST profile, not proof of production dtype,
BAR mapping, DMA alignment, NPU/PCIe gate success or FPGA Attention support.
No silent CPU fallback, protocol compatibility guessing, or KV-appending retries.

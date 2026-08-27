# VLSI Agent

An LLM-powered Verilog simulation agent that automatically generates testbenches, compiles, runs simulations, and fixes failing test cases.

## The Big Picture

In hardware design, writing the RTL (Register Transfer Level) is only half the battle. The other half is **verification** — proving that your digital logic actually does what you intended. Traditionally, this means manually writing testbenches: stimulus generators that exercise every input combination and check outputs against expected values.

This is tedious, error-prone, and a major bottleneck. A simple 4-bit ALU with 8 operations needs hundreds of test vectors to achieve reasonable coverage. A processor pipeline? Orders of magnitude more.

**VLSI Agent bridges that gap.** You write the hardware — the gates, the ALUs, the FSMs, the datapaths — and the agent handles verification automatically:

- **You design the circuit** in Verilog (combinational logic, sequential blocks, modules with port lists)
- **The agent understands your design** — it parses port declarations, width specifications, and module hierarchy
- **It generates targeted testbenches** that exercise edge cases (zero, max, carry propagation, overflow)
- **It compiles and simulates** using Icarus Verilog, the same open-source toolchain used in industry and academia
- **It reads the waveforms** (VCD files) to visualize digital signal transitions on a timing diagram
- **It self-corrects** — if a testbench fails to compile or produces wrong results, the LLM analyzes the failure and rewrites the testbench while leaving your RTL untouched

Think of it as a **verification co-pilot** for digital design. Whether you're prototyping a RISC-V core, debugging a memory controller, or validating a custom FPGA module, VLSI Agent turns the most time-consuming part of the design flow into a single click.

### What This Means for Hardware Engineers

| Traditional Flow | With VLSI Agent |
|---|---|
| Write RTL manually | Write RTL manually |
| Write testbench manually (hours) | Paste RTL → agent generates testbench (seconds) |
| Debug testbench compile errors | Agent auto-fixes compile errors |
| Manually trace waveforms | Agent renders interactive waveform viewer |
| Manually check PASS/FAIL | Agent shows expected vs actual value table |
| Iterate when tests fail | Agent retries up to 3 times with LLM fixes |

The agent currently supports **combinational logic** (gates, ALUs, muxes, decoders) with plans to expand to sequential designs (flip-flops, counters, FSMs).

## What It Does

You paste a Verilog module → the agent:

1. **Generates a testbench** using an LLM (BluesMinds API / GLM-5.2)
2. **Compiles** with Icarus Verilog (`iverilog`)
3. **Runs** the simulation (`vvp`)
4. **Analyzes** PASS/FAIL results
5. **Auto-fixes** compile errors or test failures via LLM
6. **Renders** waveforms (VCD) and an ideal values table

If the LLM fails after 3 attempts, a built-in fallback testbench covers all operations automatically.

## Architecture

```
Browser (static/index.html)
    │
    │  POST /api/simulate { verilog_code }
    │
    ▼
FastAPI (server.py :8000)
    │
    ├─── LLM (BluesMinds API / GLM-5.2)
    │     ├── generate_testbench()    → tb.v
    │     ├── analyze_failure()       → JSON fix
    │     └── build_ideal_values()    → PASS/FAIL table
    │
    ├─── Icarus Verilog
    │     ├── iverilog  → sim.vvp
    │     └── vvp       → wave.vcd + stdout
    │
    └─── Response
          ├── logs (compile/sim output per attempt)
          ├── waveform_data (parsed VCD)
          ├── test_summary (pass/fail/total)
          ├── ideal_values (table)
          └── testbench (final version)
```

## Requirements

- Python 3.10+
- [Icarus Verilog](https://github.com/steveicarus/iverilog) (`iverilog`, `vvp`)
- BluesMinds API key (sign up at https://api.bluesminds.com/sign-up?aff=JFfN)

## Setup

```bash
pip install -r requirements.txt
```

Create `.env`:

```
LLM_API_KEY=your_bluesminds_key_here
LLM_MODEL=glm-5.2
LLM_BASE_URL=https://api.bluesminds.com/v1
```

Run:

```bash
python server.py
```

Open `http://localhost:8000`.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Frontend UI |
| `/api/simulate` | POST | Run simulation pipeline |
| `/api/waveform/{run_id}` | GET | Download raw VCD file |

### POST /api/simulate

```json
{
  "verilog_code": "module alu (...); endmodule",
  "mode": "auto"
}
```

Response includes: `run_id`, `success`, `testbench`, `logs`, `waveform_data`, `ideal_values`, `test_summary`, `vcd_available`.

## Example

Click **Load Example** in the UI to get a 4-bit ALU, then click **Run**. The agent will:

- Generate a testbench covering ADD, SUB, AND, OR, XOR, NOT, GT, EQ
- Compile and simulate
- Show PASS/FAIL results in the Output tab
- Display the testbench in the Testbench tab
- Show expected vs actual values in the Ideal Values tab
- Render digital waveforms in the Waveform tab

## Files

```
server.py              # FastAPI backend + simulation pipeline
static/index.html      # Frontend SPA (CodeMirror editor, waveform viewer)
requirements.txt       # Python dependencies
.env                   # API keys (not committed)
simulations/           # Per-run artifacts (design.v, tb.v, wave.vcd)
```

# VLSI Agent

An LLM-powered Verilog simulation agent that automatically generates testbenches, compiles, runs simulations, and fixes failing test cases.

## What It Does

You paste a Verilog module → the agent:

1. **Generates a testbench** using an LLM (Groq API)
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
    ├─── LLM (Groq API)
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
- Groq API key (or OpenRouter)

## Setup

```bash
pip install -r requirements.txt
```

Create `.env`:

```
GROQ_API_KEY=your_key_here
LLM_MODEL=openai/gpt-oss-120b
LLM_BASE_URL=https://api.groq.com/openai/v1
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

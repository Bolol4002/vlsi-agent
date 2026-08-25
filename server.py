import os
import re
import json
import uuid
import shutil
import asyncio
import subprocess
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

app = FastAPI(title="VLSI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SIM_DIR = Path(__file__).parent / "simulations"
SIM_DIR.mkdir(exist_ok=True)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "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")
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")


class CodeRequest(BaseModel):
    verilog_code: str
    mode: str = "auto"


class LLMChatMessage(BaseModel):
    role: str
    content: str


def run_command(cmd: list[str], cwd: str, timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Simulation timed out"
    except Exception as e:
        return 1, "", str(e)


def parse_vcd(vcd_path: str) -> dict:
    signals = {}
    current_scope = ""
    signal_map = {}

    try:
        with open(vcd_path, "r") as f:
            lines = f.readlines()
    except Exception:
        return {"signals": {}, "timeline": []}

    timeline = []
    current_time = 0

    for line in lines:
        line = line.strip()

        if line.startswith("$scope"):
            parts = line.split()
            if len(parts) >= 3:
                current_scope = parts[2]
        elif line.startswith("$upscope"):
            current_scope = ""
        elif line.startswith("$var"):
            parts = line.split()
            if len(parts) >= 5:
                var_id = parts[3]
                var_name = parts[4]
                signal_map[var_id] = var_name
                full_name = f"{current_scope}.{var_name}" if current_scope else var_name
                signals[var_name] = {"name": var_name, "scope": current_scope, "values": []}
        elif line.startswith("#"):
            try:
                current_time = int(line[1:])
                timeline.append(current_time)
            except ValueError:
                pass
        elif line and line[0] in "01xzXZ":
            if len(line) > 1:
                value = line[0]
                var_id = line[1:]
                if var_id in signal_map:
                    sig_name = signal_map[var_id]
                    if sig_name not in signals:
                        signals[sig_name] = {"name": sig_name, "scope": "", "values": []}
                    signals[sig_name]["values"].append({"time": current_time, "value": value})

    return {"signals": signals, "timeline": timeline}


async def call_llm(messages: list[dict], temperature: float = 0.3) -> str:
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENROUTER_API_KEY not set. Set it as an environment variable."
        )

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 4096,
            },
        )
        if resp.status_code != 200:
            detail = resp.text
            raise HTTPException(status_code=500, detail=f"LLM API error: {detail}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def extract_code_block(text: str, lang: str = "") -> str:
    patterns = [
        rf"```{lang}\s*\n(.*?)```",
        r"```\s*\n(.*?)```",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return text.strip()


async def generate_testbench(verilog_code: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Generate a Verilog testbench. Rules:\n"
                "- Output ONLY a ```verilog code block\n"
                "- Module name MUST be 'tb'\n"
                "- Use $dumpfile(\"wave.vcd\") and $dumpvars(0, tb)\n"
                "- Use $display with PASS/FAIL per test case showing expected vs actual\n"
                "- Include 5-8 test cases (normal + edge cases)\n"
                "- End with $finish, use #10 delays between tests"
            ),
        },
        {
            "role": "user",
            "content": f"Generate a testbench for this Verilog module:\n\n```verilog\n{verilog_code}\n```",
        },
    ]
    response = await call_llm(messages)
    return extract_code_block(response, "verilog")


async def analyze_failure(
    verilog_code: str, testbench: str, stdout: str, stderr: str
) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "Debug failed Verilog simulation. Return JSON:\n"
                '{"analysis":"issue","fix_type":"verilog|testbench|both",'
                '"verilog_code":"fixed code if needed","testbench":"fixed tb if needed",'
                '"explanation":"what was wrong"}\n'
                "Fix code for compile errors, fix testbench for FAIL mismatches. JSON only, no markdown."
            ),
        },
        {
            "role": "user",
            "content": (
                f"CODE:\n{verilog_code}\n\nTB:\n{testbench}\n\nOUTPUT:\n{stdout}\n{stderr}"
            ),
        },
    ]
    response = await call_llm(messages, temperature=0.2)
    cleaned = response.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "analysis": "Could not parse LLM response",
            "fix_type": "none",
            "verilog_code": verilog_code,
            "testbench": testbench,
            "explanation": cleaned,
        }


async def generate_ideal_values(verilog_code: str, testbench: str) -> str:
    messages = [
        {
            "role": "system",
            "content": "Analyze expected values for each test case. Output a table: Test Case | Inputs | Expected Outputs",
        },
        {
            "role": "user",
            "content": f"MODULE:\n{verilog_code}\n\nTB:\n{testbench}",
        },
    ]
    response = await call_llm(messages, temperature=0.1)
    return response


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))


@app.post("/api/simulate")
async def simulate(req: CodeRequest):
    run_id = str(uuid.uuid4())[:8]
    work_dir = str(SIM_DIR / run_id)
    os.makedirs(work_dir, exist_ok=True)

    vcd_path = os.path.join(work_dir, "wave.vcd")
    vlog_file = os.path.join(work_dir, "design.v")
    tb_file = os.path.join(work_dir, "tb.v")
    exe_file = os.path.join(work_dir, "sim.vvp")

    with open(vlog_file, "w") as f:
        f.write(req.verilog_code)

    max_attempts = 5
    current_verilog = req.verilog_code
    current_testbench = None
    all_logs = []
    waveform_data = None
    test_results = []
    ideal_values = ""
    success = False

    for attempt in range(max_attempts):
        if current_testbench is None:
            current_testbench = await generate_testbench(current_verilog)

        with open(tb_file, "w") as f:
            f.write(current_testbench)

        log_entry = {"attempt": attempt + 1, "testbench": current_testbench}

        compile_code, compile_out, compile_err = run_command(
            ["iverilog", "-o", exe_file, vlog_file, tb_file], work_dir
        )

        if compile_code != 0:
            log_entry["compile_error"] = True
            log_entry["stdout"] = compile_out
            log_entry["stderr"] = compile_err
            all_logs.append(log_entry)

            fix = await analyze_failure(
                current_verilog, current_testbench, compile_out, compile_err
            )
            if fix.get("fix_type") in ("verilog", "both"):
                current_verilog = fix.get("verilog_code", current_verilog)
                with open(vlog_file, "w") as f:
                    f.write(current_verilog)
            if fix.get("fix_type") in ("testbench", "both"):
                current_testbench = fix.get("testbench", current_testbench)
            log_entry["fix"] = fix
            continue

        sim_code, sim_out, sim_err = run_command(
            ["vvp", exe_file], work_dir, timeout=60
        )

        log_entry["compile_error"] = False
        log_entry["stdout"] = sim_out
        log_entry["stderr"] = sim_err
        all_logs.append(log_entry)

        if sim_out and "FAIL" not in sim_out.upper():
            success = True
            break

        if sim_out and "PASS" in sim_out.upper() and "FAIL" not in sim_out.upper():
            success = True
            break

        fix = await analyze_failure(
            current_verilog, current_testbench, sim_out, sim_err
        )
        if fix.get("fix_type") in ("verilog", "both"):
            current_verilog = fix.get("verilog_code", current_verilog)
            with open(vlog_file, "w") as f:
                f.write(current_verilog)
        if fix.get("fix_type") in ("testbench", "both"):
            current_testbench = fix.get("testbench", current_testbench)
        log_entry["fix"] = fix

    if os.path.exists(vcd_path):
        waveform_data = parse_vcd(vcd_path)

    ideal_values = await generate_ideal_values(current_verilog, current_testbench)

    pass_count = 0
    fail_count = 0
    for log in all_logs:
        stdout = log.get("stdout", "")
        pass_count += stdout.upper().count("PASS")
        fail_count += stdout.upper().count("FAIL")

    return {
        "run_id": run_id,
        "success": success,
        "attempts": len(all_logs),
        "verilog_code": current_verilog,
        "testbench": current_testbench,
        "logs": all_logs,
        "waveform_data": waveform_data,
        "ideal_values": ideal_values,
        "test_summary": {
            "passed": pass_count,
            "failed": fail_count,
            "total": pass_count + fail_count,
        },
        "vcd_available": os.path.exists(vcd_path),
        "work_dir": work_dir,
    }


@app.get("/api/waveform/{run_id}")
async def get_waveform(run_id: str):
    vcd_path = SIM_DIR / run_id / "wave.vcd"
    if not vcd_path.exists():
        raise HTTPException(status_code=404, detail="Waveform not found")
    return FileResponse(str(vcd_path), media_type="text/plain")


app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

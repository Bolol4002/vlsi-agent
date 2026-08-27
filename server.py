import os
import re
import json
import uuid
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv
<<<<<<< HEAD
=======

load_dotenv(Path(__file__).parent / ".env")
>>>>>>> cde7631 (aomw)

app = FastAPI(title="VLSI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SIM_DIR = Path(__file__).parent / "simulations"
SIM_DIR.mkdir(exist_ok=True)

<<<<<<< HEAD
load_dotenv(Path(__file__).parent / ".env")

LLM_API_KEY = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
=======
LLM_API_KEY = os.environ.get("GROQ_API_KEY")
>>>>>>> cde7631 (aomw)
LLM_MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")


class CodeRequest(BaseModel):
    verilog_code: str
    mode: str = "auto"


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
    signal_map = {}
    signal_widths = {}

    try:
        with open(vcd_path, "r") as f:
            lines = f.readlines()
    except Exception:
        return {"signals": {}, "timeline": []}

    timeline = []
    current_time = 0

    for line in lines:
        line = line.strip()

        if line.startswith("$var"):
            parts = line.split()
            if len(parts) >= 5:
                var_id = parts[3]
                var_name = parts[4]
                width = int(parts[2]) if parts[2].isdigit() else 1
                signal_map[var_id] = var_name
                signal_widths[var_id] = width
                if var_name not in signals:
                    signals[var_name] = {"name": var_name, "values": []}
        elif line.startswith("#"):
            try:
                current_time = int(line[1:])
                timeline.append(current_time)
            except ValueError:
                pass
        elif line.startswith("b"):
            parts = line.split()
            if len(parts) == 2:
                raw_val = parts[0][1:]
                var_id = parts[1]
                if var_id in signal_map:
                    sig_name = signal_map[var_id]
                    if sig_name not in signals:
                        signals[sig_name] = {"name": sig_name, "values": []}
                    signals[sig_name]["values"].append({
                        "time": current_time,
                        "value": raw_val,
                        "width": signal_widths.get(var_id, len(raw_val)),
                    })
        elif line and line[0] in "01xzXZ" and len(line) > 1:
            value = line[0]
            var_id = line[1:]
            if var_id in signal_map:
                sig_name = signal_map[var_id]
                if sig_name not in signals:
                    signals[sig_name] = {"name": sig_name, "values": []}
                width = signal_widths.get(var_id, 1)
                signals[sig_name]["values"].append({
                    "time": current_time,
                    "value": value if width == 1 else value.zfill(width),
                    "width": width,
                })

    for sig in signals.values():
        vals = sig["values"]
        deduped = []
        seen_times = {}
        for v in vals:
            t = v["time"]
            if t in seen_times:
                deduped[seen_times[t]] = v
            else:
                seen_times[t] = len(deduped)
                deduped.append(v)
        sig["values"] = deduped

    return {"signals": signals, "timeline": timeline}


<<<<<<< HEAD
async def call_llm(
    messages: list[dict], temperature: float = 0.3, max_tokens: int = 1200
) -> str:
    if not LLM_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY not set. Add it to the .env file.",
=======
async def call_llm(messages: list[dict], temperature: float = 0.3) -> str:
    if not LLM_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY not set. Add it to the .env file."
>>>>>>> cde7631 (aomw)
        )

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"LLM API error: {resp.text}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def extract_code_block(text: str, lang: str = "") -> str:
    cleaned = text.strip()

    language = re.escape(lang) if lang else r"[\w+-]+"
    fenced = re.search(
        rf"```(?:{language})?\s*\n?(.*?)```", cleaned, re.IGNORECASE | re.DOTALL
    )
    if fenced:
        content = fenced.group(1).strip()
        if content:
            return content

    fenced_any = re.search(r"```\w*\s*\n?(.*?)```", cleaned, re.DOTALL)
    if fenced_any:
        content = fenced_any.group(1).strip()
        if content:
            return content

    lines = cleaned.split("\n")
    start = -1
    end = len(lines)
    for i, l in enumerate(lines):
        if l.strip().startswith("```"):
            start = i + 1
            break
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "```":
            end = i
            break
    if start >= 0:
        content = "\n".join(lines[start:end]).strip()
        if content:
            return content

    if "module" in cleaned:
        module_match = re.search(
            r"(module\s+\w+.*?endmodule)", cleaned, re.DOTALL | re.IGNORECASE
        )
        if module_match:
            return module_match.group(1).strip()

    return cleaned


def validate_testbench(tb: str) -> bool:
    if not tb or not tb.strip():
        return False
    stripped = tb.strip()
    if stripped.startswith("```"):
        return False
    if "module" not in stripped:
        return False
    if "endmodule" not in stripped.lower():
        return False
    return True


async def generate_testbench(verilog_code: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Verilog testbench generator. Rules:\n"
                "1. Output ONLY ```verilog code block\n"
                "2. Module name: tb\n"
                "3. `timescale 1ns/1ps\n"
                "4. $dumpfile + $dumpvars\n"
                "5. 5 PASS/FAIL tests, $finish at end\n"
                "6. No comments. Compact code only."
            ),
        },
        {
            "role": "user",
            "content": f"TB for:\n```verilog\n{verilog_code}\n```",
        },
    ]
    for attempt in range(3):
        response = await call_llm(messages, max_tokens=2000)
        tb = extract_code_block(response, "verilog")
        if validate_testbench(tb):
            return tb
    return ""


async def analyze_failure(
    verilog_code: str, testbench: str, stdout: str, stderr: str
) -> dict:
    messages = [
        {
            "role": "system",
            "content": (
                "Debug Verilog simulation failure. Return JSON only:\n"
                '{"analysis":"issue","fix_type":"verilog|testbench|both",'
                '"verilog_code":"fixed code","testbench":"fixed testbench",'
                '"explanation":"what was wrong"}'
            ),
        },
        {
            "role": "user",
            "content": (
                f"CODE:\n```verilog\n{verilog_code}\n```\n"
                f"TB:\n```verilog\n{testbench}\n```\n"
                f"OUTPUT:\n{stdout}\n{stderr}"
            ),
        },
    ]
    response = await call_llm(messages, temperature=0.2, max_tokens=2000)
    cleaned = response.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)

    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

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


def build_ideal_values(logs: list[dict]) -> str:
    rows = []
    pattern = re.compile(
        r"(PASS|FAIL):\s*(.*?)\s*=>\s*expected=([^,]+),?\s*actual=(.*)"
    )
    pattern2 = re.compile(
        r"(PASS|FAIL):\s*op=(\S+)\s*a=(\S+)\s*b=(\S+)\s*=>\s*expected=(\S+)\s*actual=(\S+)"
    )
    for log in logs:
        for line in log.get("stdout", "").splitlines():
            m1 = pattern.search(line)
            m2 = pattern2.search(line)
            if m1:
                status = m1.group(1)
                rows.append(
                    f"| {m1.group(2)} | {m1.group(3)} | {m1.group(4)} | {status} |"
                )
            elif m2:
                status = m2.group(1)
                op, a_val, b_val = m2.group(2), m2.group(3), m2.group(4)
                exp, act = m2.group(5), m2.group(6)
                rows.append(
                    f"| op={op} a={a_val} b={b_val} | {exp} | {act} | {status} |"
                )
    if not rows:
        return ""
    return (
        "| Test Case | Expected | Actual | Status |\n"
        "| --- | --- | --- | --- |\n"
        + "\n".join(rows)
    )


FALLBACK_TB_TEMPLATE = """\
`timescale 1ns/1ps
module tb;
    reg [3:0] a, b;
    reg [2:0] op;
    wire [3:0] result;
    reg [3:0] exp;
    integer pass_cnt, fail_cnt;
    alu dut (.a(a), .b(b), .op(op), .result(result));
    task check;
        input [3:0] expected;
        begin
            #1;
            if (result === expected) begin
                $display("PASS: op=%b a=%0d b=%0d => expected=%0d actual=%0d", op, a, b, expected, result);
                pass_cnt = pass_cnt + 1;
            end else begin
                $display("FAIL: op=%b a=%0d b=%0d => expected=%0d actual=%0d", op, a, b, expected, result);
                fail_cnt = fail_cnt + 1;
            end
        end
    endtask
    initial begin
        $dumpfile("wave.vcd");
        $dumpvars(0, tb);
        pass_cnt = 0; fail_cnt = 0;
        a=4'd3;  b=4'd5;  op=3'b000; #1; check(4'd8);
        a=4'd9;  b=4'd1;  op=3'b000; #1; check(4'd10);
        a=4'd7;  b=4'd2;  op=3'b001; #1; check(4'd5);
        a=4'd0;  b=4'd1;  op=3'b001; #1; check(4'd15);
        a=4'b1010; b=4'b1100; op=3'b010; #1; check(4'b1000);
        a=4'b0101; b=4'b0011; op=3'b011; #1; check(4'b0111);
        a=4'b1111; b=4'b1010; op=3'b100; #1; check(4'b0101);
        a=4'b0011; b=4'bxxxx; op=3'b101; #1; check(4'b1100);
        a=4'd9;  b=4'd4;  op=3'b110; #1; check(4'd1);
        a=4'd3;  b=4'd7;  op=3'b110; #1; check(4'd0);
        a=4'd5;  b=4'd5;  op=3'b111; #1; check(4'd1);
        a=4'd2;  b=4'd6;  op=3'b111; #1; check(4'd0);
        #10 $finish;
    end
endmodule"""


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

    max_attempts = 3
    current_verilog = req.verilog_code
    current_testbench = None
    all_logs = []
    waveform_data = None
    success = False

    for attempt in range(max_attempts):
        if current_testbench is None or not validate_testbench(current_testbench):
            current_testbench = await generate_testbench(current_verilog)

        if not validate_testbench(current_testbench):
            current_testbench = FALLBACK_TB_TEMPLATE

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
                tb_from_fix = fix.get("testbench", "")
                if validate_testbench(tb_from_fix):
                    current_testbench = tb_from_fix
                else:
                    current_testbench = None
            log_entry["fix"] = fix
            continue

        sim_code, sim_out, sim_err = run_command(
            ["vvp", exe_file], work_dir, timeout=60
        )

        log_entry["compile_error"] = False
        log_entry["stdout"] = sim_out
        log_entry["stderr"] = sim_err
        all_logs.append(log_entry)

        has_fail = "FAIL" in sim_out.upper() if sim_out else True
        has_pass = "PASS" in sim_out.upper() if sim_out else False

        if has_pass and not has_fail:
            success = True
            break

        if attempt == max_attempts - 1:
            break

        fix = await analyze_failure(
            current_verilog, current_testbench, sim_out, sim_err
        )
        if fix.get("fix_type") in ("verilog", "both"):
            current_verilog = fix.get("verilog_code", current_verilog)
            with open(vlog_file, "w") as f:
                f.write(current_verilog)
        if fix.get("fix_type") in ("testbench", "both"):
            tb_from_fix = fix.get("testbench", "")
            if validate_testbench(tb_from_fix):
                current_testbench = tb_from_fix
            else:
                current_testbench = None
        log_entry["fix"] = fix

    if os.path.exists(vcd_path):
        waveform_data = parse_vcd(vcd_path)

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
        "ideal_values": build_ideal_values(all_logs),
        "test_summary": {
            "passed": pass_count,
            "failed": fail_count,
            "total": pass_count + fail_count,
        },
        "vcd_available": os.path.exists(vcd_path),
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

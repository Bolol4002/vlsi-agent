import os
import re
import json
import uuid
import asyncio
import subprocess
from pathlib import Path
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

# ── Configuration ──────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

LLM_API_KEY = os.environ.get("LLM_API_KEY")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder-16k:latest")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://aiapi.picturethis.work/v1")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://aiapi.picturethis.work")
USE_OLLAMA_NATIVE = os.environ.get("USE_OLLAMA_NATIVE", "false").lower() == "true"
MAX_ATTEMPTS = 3
IVERILOG_TIMEOUT = 30
VVP_TIMEOUT = 60
LLM_TIMEOUT = 120
# Qwen2.5-Coder (local Ollama): low-entropy decode, ChatML stop tokens
LLM_TEMPERATURE = 0.1
LLM_TOP_P = 0.8
LLM_MAX_TOKENS = 1536
_QWEN_STOP = ["<|im_end|>", "<|endoftext|>"]

# ── App Setup ──────────────────────────────────────────────────────────────────
app = FastAPI(title="VLSI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SIM_DIR = Path(__file__).parent / "simulations"
SIM_DIR.mkdir(exist_ok=True)


# ── Persistent HTTP Client ─────────────────────────────────────────────────────
_http_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    """Reuse a single HTTP client across requests for connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=LLM_TIMEOUT)
    return _http_client


class CodeRequest(BaseModel):
    verilog_code: str
    mode: str = "auto"


# ── Utility: Run External Command ──────────────────────────────────────────────
def run_command(
    cmd: list[str], cwd: str, timeout: int = IVERILOG_TIMEOUT
) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Simulation timed out"
    except Exception as e:
        return 1, "", str(e)


# ── VCD Parser ─────────────────────────────────────────────────────────────────
def parse_vcd(vcd_path: str) -> dict:
    """Parse a Value Change Dump file into structured signal data."""
    try:
        with open(vcd_path, "r") as f:
            lines = f.readlines()
    except Exception:
        return {"signals": {}, "timeline": []}

    signals: dict[str, dict] = {}
    signal_map: dict[str, str] = {}
    signal_widths: dict[str, int] = {}
    timeline: list[int] = []
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
                    signals[sig_name]["values"].append(
                        {
                            "time": current_time,
                            "value": raw_val,
                            "width": signal_widths.get(var_id, len(raw_val)),
                        }
                    )

        elif line and line[0] in "01xzXZ" and len(line) > 1:
            value = line[0]
            var_id = line[1:]
            if var_id in signal_map:
                sig_name = signal_map[var_id]
                if sig_name not in signals:
                    signals[sig_name] = {"name": sig_name, "values": []}
                width = signal_widths.get(var_id, 1)
                signals[sig_name]["values"].append(
                    {
                        "time": current_time,
                        "value": value if width == 1 else value.zfill(width),
                        "width": width,
                    }
                )

    # Deduplicate values per time step (keep last value for each time)
    for sig in signals.values():
        seen_times: dict[int, int] = {}
        deduped: list[dict] = []
        for v in sig["values"]:
            t = v["time"]
            if t in seen_times:
                deduped[seen_times[t]] = v
            else:
                seen_times[t] = len(deduped)
                deduped.append(v)
        sig["values"] = deduped

    return {"signals": signals, "timeline": timeline}


# ── LLM Caller ─────────────────────────────────────────────────────────────────
def _qwen_chatml(messages: list[dict]) -> str:
    """Qwen2.5-Coder Instruct chat template (for native Ollama /api/generate)."""
    parts: list[str] = []
    for m in messages:
        parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


async def call_llm(
    messages: list[dict],
    temperature: float = LLM_TEMPERATURE,
    max_tokens: int = LLM_MAX_TOKENS,
) -> str:
    """Call local Qwen2.5-Coder via Ollama (OpenAI-compat or native)."""
    if not LLM_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="LLM_API_KEY not set. Add it to the .env file.",
        )

    client = await get_http_client()
    last_error = None

    for retry in range(2):
        try:
            if USE_OLLAMA_NATIVE:
                resp = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    headers={
                        "Authorization": f"Bearer {LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": LLM_MODEL,
                        "prompt": _qwen_chatml(messages),
                        "stream": False,
                        "stop": _QWEN_STOP,
                        "options": {
                            "temperature": temperature,
                            "top_p": LLM_TOP_P,
                            "num_predict": max_tokens,
                            "repeat_penalty": 1.05,
                        },
                    },
                )
            else:
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
                        "top_p": LLM_TOP_P,
                        "max_tokens": max_tokens,
                        "stop": _QWEN_STOP,
                    },
                )

            if resp.status_code == 429:
                if retry == 0:
                    await asyncio.sleep(2)
                    continue
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail=f"LLM API error ({resp.status_code}): {resp.text}",
                )

            data = resp.json()
            if USE_OLLAMA_NATIVE:
                return data.get("response", "") or ""
            choices = data.get("choices") or []
            if not choices:
                last_error = "empty LLM choices"
                continue
            return (choices[0].get("message") or {}).get("content") or ""

        except httpx.TimeoutException:
            last_error = "LLM request timed out"
            continue
        except httpx.ConnectError:
            last_error = "Cannot connect to LLM API"
            continue

    raise HTTPException(status_code=502, detail=f"LLM API failed: {last_error}")


# ── Code Extraction & Validation ───────────────────────────────────────────────
def extract_code_block(text: str, lang: str = "") -> str:
    """Extract a fenced code block from LLM response text."""
    cleaned = text.strip()

    # Try language-specific fenced block first
    language = re.escape(lang) if lang else r"[\w+-]+"
    fenced = re.search(
        rf"```(?:{language})?\s*\n?(.*?)```", cleaned, re.IGNORECASE | re.DOTALL
    )
    if fenced:
        content = fenced.group(1).strip()
        if content:
            return content

    # Try any fenced block
    fenced_any = re.search(r"```\w*\s*\n?(.*?)```", cleaned, re.DOTALL)
    if fenced_any:
        content = fenced_any.group(1).strip()
        if content:
            return content

    # Try to find module...endmodule
    if "module" in cleaned:
        module_match = re.search(
            r"(module\s+\w+.*?endmodule)", cleaned, re.DOTALL | re.IGNORECASE
        )
        if module_match:
            return module_match.group(1).strip()

    return cleaned


def validate_testbench(tb: str, dut_name: str | None = None) -> bool:
    """Validate that a string looks like a proper Verilog testbench."""
    if not tb or not tb.strip():
        return False
    stripped = tb.strip()
    if stripped.startswith("```"):
        return False
    if not re.search(r"\bmodule\s+tb\b", stripped, re.IGNORECASE):
        return False
    if "endmodule" not in stripped.lower():
        return False
    if "$finish" not in stripped:
        return False
    if dut_name and not re.search(rf"\b{re.escape(dut_name)}\s+\w+\s*\(", stripped):
        return False
    return True


def _qwen_tb_messages(verilog_code: str, dut: dict | None) -> list[dict]:
    """Short, DUT-locked prompt — Qwen2.5-Coder follows examples, not long rule lists."""
    if dut:
        decls, inst = _dut_decls_and_instance(dut)
        port_lines = "\n".join(
            f"  {p['direction']} {p['width'] + ' ' if p['width'] else ''}{p['name']}"
            for p in dut["ports"]
        )
        dut_name = dut["name"]
        inst_line = inst.strip()
    else:
        decls, inst = "    // declare reg for inputs, wire for outputs", "    // DUT dut (...);"
        port_lines = "  (see source)"
        dut_name = "(see source)"
        inst_line = "<DUT_NAME> dut (.<port>(<port>), ...);"

    system = (
        "You are Qwen2.5-Coder. Write a Verilog testbench.\n"
        "Reply with one ```verilog block only. No prose, no markdown outside the block."
    )
    user = (
        f"Language: Verilog-2001 (iverilog).\n"
        f"DUT name: {dut_name}\n"
        f"Ports:\n{port_lines}\n\n"
        f"DUT source (do not modify, do not copy into the testbench as a second module):\n"
        f"```verilog\n{verilog_code}\n```\n\n"
        f"Copy this skeleton. Keep the instantiation line EXACTLY:\n"
        f"```verilog\n"
        f"`timescale 1ns/1ps\n"
        f"module tb;\n"
        f"{decls}\n"
        f"{inst}\n"
        f"    initial begin\n"
        f'        $dumpfile("wave.vcd");\n'
        f"        $dumpvars(0, tb);\n"
        f"        // tests\n"
        f"        $finish;\n"
        f"    end\n"
        f"endmodule\n"
        f"```\n\n"
        f"Required instance line:\n    {inst_line}\n\n"
        f"Rules:\n"
        f"- module name is tb. Exactly one initial begin.\n"
        f"- Instantiate ONLY {dut_name}. Never invent a name like test_adder or uut_mod.\n"
        f"- Example display (put real values, never the words desc or <v>):\n"
        f"    $display(\"PASS: A=0 B=0 => expected=0 actual=%0d\", Sum);\n"
        f"    $display(\"FAIL: A=0 B=0 => expected=0 actual=%0d\", Sum);\n"
        f"- Literals must match signal width (1-bit: 1'b0; 4-bit: 4'h7). Never -1 on an unsigned bus.\n"
        f"- At least 4 test cases. No comments."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── LLM: Generate Testbench ───────────────────────────────────────────────────
async def generate_testbench(verilog_code: str) -> str:
    """Generate a testbench: combinational golden (gates/ALU), else Qwen."""
    dut = parse_dut(verilog_code)
    dut_name = dut["name"] if dut else None
    gate_tb = generate_gate_testbench(verilog_code)
    if validate_testbench(gate_tb, dut_name):
        return gate_tb

    messages = _qwen_tb_messages(verilog_code, dut)

    for attempt in range(3):
        response = await call_llm(messages)
        tb = repair_testbench(extract_code_block(response, "verilog"), dut)
        if validate_testbench(tb, dut_name):
            return tb

        messages.append({"role": "assistant", "content": response})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Invalid. Output one ```verilog block.\n"
                    f"module tb; instantiate {dut_name or 'the DUT'} exactly as:\n"
                    f"    {( _dut_decls_and_instance(dut)[1].strip() if dut else 'DUT dut (...);') }\n"
                    f"One initial begin, $dumpfile, $dumpvars, PASS/FAIL $display, $finish."
                ),
            }
        )

    if dut:
        return repair_testbench(generate_fallback_testbench(verilog_code), dut)
    return ""


# ── LLM: Analyze Failure ──────────────────────────────────────────────────────
async def analyze_failure(
    verilog_code: str, testbench: str, stdout: str, stderr: str
) -> dict:
    """Ask Qwen to rewrite the testbench only. Never rewrite the DUT.

    Local Qwen2.5-Coder (3B/16k) cannot reliably emit JSON or safely patch
    the design; it hallucinates DUT names and 'fixes' working RTL.
    """
    stdout_tail = stdout[-1500:] if len(stdout) > 1500 else stdout
    stderr_tail = stderr[-1500:] if len(stderr) > 1500 else stderr
    dut = parse_dut(verilog_code)
    dut_name = dut["name"] if dut else "the DUT"
    inst_line = _dut_decls_and_instance(dut)[1].strip() if dut else ""

    messages = [
        {
            "role": "system",
            "content": (
                "You are Qwen2.5-Coder. Fix a Verilog testbench.\n"
                "Reply with one ```verilog block only. Do not modify the DUT. Do not write JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f"DUT name: {dut_name} (do not change this module)\n"
                f"Required instance line: {inst_line}\n\n"
                f"DUT:\n```verilog\n{verilog_code}\n```\n\n"
                f"Broken testbench:\n```verilog\n{testbench}\n```\n\n"
                f"iverilog/vvp output:\n{stderr_tail}\n{stdout_tail}\n\n"
                f"Write a corrected `module tb`. Instantiate {dut_name} with the required "
                f"instance line. One initial begin, $dumpfile(\"wave.vcd\"), $dumpvars(0, tb), "
                f"PASS/FAIL $display, $finish."
            ),
        },
    ]

    response = await call_llm(messages)
    tb = repair_testbench(extract_code_block(response, "verilog"), dut)
    if validate_testbench(tb, dut["name"] if dut else None):
        return {
            "analysis": "Rewrote testbench to match DUT ports/name",
            "fix_type": "testbench",
            "verilog_code": verilog_code,
            "testbench": tb,
            "explanation": "Corrected testbench only; DUT left unchanged.",
        }
    return {
        "analysis": "Coder could not produce a valid testbench fix",
        "fix_type": "none",
        "verilog_code": verilog_code,
        "testbench": testbench,
        "explanation": (response or "")[:500],
    }


# Token-safe PASS/FAIL: do not match FAILED, FAILURE, PASSED, COMPASS, etc.
_TEST_RESULT_RE = re.compile(r"(?<![A-Za-z_])(PASS|FAIL)(?![A-Za-z_])", re.IGNORECASE)


def count_pass_fail(stdout: str) -> tuple[int, int]:
    """Count PASS/FAIL test results in simulator stdout."""
    passed = failed = 0
    for m in _TEST_RESULT_RE.finditer(stdout or ""):
        if m.group(1).upper() == "PASS":
            passed += 1
        else:
            failed += 1
    return passed, failed


def last_sim_log(logs: list[dict]) -> dict | None:
    """Return the most recent log from a run that actually simulated."""
    for log in reversed(logs):
        if not log.get("compile_error"):
            return log
    return None


# ── Build Ideal Values Table ──────────────────────────────────────────────────
def build_ideal_values(logs: list[dict]) -> str:
    """Parse PASS/FAIL output lines and build a markdown table."""
    rows: list[str] = []
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


# ── Fallback Testbench ────────────────────────────────────────────────────────
_VERILOG_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_VERILOG_LINE_COMMENT = re.compile(r"//.*?$", re.MULTILINE)
_PORT_IDENT = r"(?!input\b|output\b|inout\b|wire\b|reg\b|logic\b)[A-Za-z_]\w*"
_PORT_DECL = re.compile(
    r"(?P<dir>input|output|inout)\s+"
    r"(?:(?:wire|reg|logic|signed|unsigned)\s+)*"
    r"(?P<width>\[[^\]]+\])?\s*"
    r"(?P<names>" + _PORT_IDENT + r"(?:\s*,\s*" + _PORT_IDENT + r")*)",
    re.IGNORECASE,
)


def _strip_verilog_comments(code: str) -> str:
    code = _VERILOG_BLOCK_COMMENT.sub("", code)
    return _VERILOG_LINE_COMMENT.sub("", code)


def parse_dut(verilog_code: str) -> dict | None:
    """Extract the first non-tb module name and its ports."""
    src = _strip_verilog_comments(verilog_code)
    for m in re.finditer(
        r"\bmodule\s+(\w+)\s*(?:#\s*\(.*?\))?\s*(?:\((.*?)\))?\s*;",
        src,
        re.DOTALL | re.IGNORECASE,
    ):
        name = m.group(1)
        if name.lower() == "tb":
            continue
        port_list = m.group(2) or ""
        body_start = m.end()
        body_end = re.search(r"\bendmodule\b", src[body_start:], re.IGNORECASE)
        body = (
            src[body_start : body_start + body_end.start()]
            if body_end
            else src[body_start:]
        )

        ports: list[dict] = []
        seen: set[str] = set()

        def add_ports(chunk: str) -> None:
            for decl in _PORT_DECL.finditer(chunk):
                direction = decl.group("dir").lower()
                width = (decl.group("width") or "").strip()
                for pname in decl.group("names").split(","):
                    pname = pname.strip()
                    if not pname or pname in seen:
                        continue
                    seen.add(pname)
                    ports.append(
                        {"name": pname, "direction": direction, "width": width}
                    )

        if re.search(r"\b(input|output|inout)\b", port_list, re.IGNORECASE):
            add_ports(port_list)
        if not ports:
            add_ports(body)
        if not ports:
            return None
        return {"name": name, "ports": ports}
    return None


def _dut_decls_and_instance(dut: dict) -> tuple[str, str]:
    """TB signal decls and a named-port DUT instantiation line."""
    decls: list[str] = []
    conns: list[str] = []
    for p in dut["ports"]:
        width = f"{p['width']} " if p["width"] else ""
        if p["direction"] in ("input", "inout"):
            decls.append(f"    reg {width}{p['name']};")
        else:
            decls.append(f"    wire {width}{p['name']};")
        conns.append(f".{p['name']}({p['name']})")
    inst = f"    {dut['name']} dut ({', '.join(conns)});"
    return "\n".join(decls), inst


def _module_body(verilog_code: str, dut_name: str) -> str:
    src = _strip_verilog_comments(verilog_code)
    m = re.search(
        rf"\bmodule\s+{re.escape(dut_name)}\s*(?:#\s*\(.*?\))?\s*(?:\((?:.*?)\))?\s*;",
        src,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return ""
    rest = src[m.end() :]
    end = re.search(r"\bendmodule\b", rest, re.IGNORECASE)
    return rest[: end.start()] if end else rest


def _eval_bit_expr(expr: str, env: dict[str, int]) -> int | None:
    """Evaluate a 1-bit Verilog expression. None if it is not a pure gate formula."""
    s = expr.strip().rstrip(";")
    s = s.replace("&&", "&").replace("||", "|")
    s = re.sub(r"\s+", "", s)
    if not s:
        return None
    s = s.replace("~^", "@").replace("^~", "@")
    tmp = s
    for name in sorted(env, key=len, reverse=True):
        tmp = re.sub(rf"\b{re.escape(name)}\b", "0", tmp)
    if re.search(r"[^01~^&|()@]", tmp):
        return None
    py = s
    for name in sorted(env, key=len, reverse=True):
        py = re.sub(rf"\b{re.escape(name)}\b", str(env[name] & 1), py)
    py = py.replace("@", "==").replace("~", "1-")
    try:
        return int(eval(py, {"__builtins__": {}}, {})) & 1  # noqa: S307
    except Exception:
        return None


def _prim_eval(kind: str, xs: list[int]) -> int:
    if kind == "and":
        v = 1
        for x in xs:
            v &= x
        return v & 1
    if kind == "nand":
        return (1 - _prim_eval("and", xs)) & 1
    if kind == "or":
        v = 0
        for x in xs:
            v |= x
        return v & 1
    if kind == "nor":
        return (1 - _prim_eval("or", xs)) & 1
    if kind == "xor":
        v = 0
        for x in xs:
            v ^= x
        return v & 1
    if kind == "xnor":
        return (1 - _prim_eval("xor", xs)) & 1
    if kind == "not":
        return (1 - xs[0]) & 1
    if kind == "buf":
        return xs[0] & 1
    raise ValueError(kind)


def parse_output_equations(verilog_code: str, dut: dict) -> dict | None:
    """Map each 1-bit output to ('expr', rhs) or ('prim', kind, [inputs])."""
    if any(p["width"] for p in dut["ports"]):
        return None
    names = {p["name"] for p in dut["ports"]}
    outputs = {p["name"] for p in dut["ports"] if p["direction"] == "output"}
    inputs = {p["name"] for p in dut["ports"] if p["direction"] in ("input", "inout")}
    if not outputs or not inputs:
        return None
    body = _module_body(verilog_code, dut["name"])
    if re.search(r"\bposedge\b|\bnegedge\b", body, re.IGNORECASE):
        return None

    eqs: dict = {}

    for m in re.finditer(
        r"\bassign\s+(\w+)\s*=\s*([^;]+);", body, re.IGNORECASE
    ):
        lhs, rhs = m.group(1), m.group(2)
        if lhs in outputs:
            eqs[lhs] = ("expr", rhs)

    for m in re.finditer(
        r"always\s*@\s*\*?\s*(?:\(\s*\*\s*\))?\s*(?:begin\s*)?(\w+)\s*=\s*([^;]+);",
        body,
        re.IGNORECASE,
    ):
        lhs, rhs = m.group(1), m.group(2)
        if lhs in outputs and lhs not in eqs:
            eqs[lhs] = ("expr", rhs)

    for m in re.finditer(
        r"\b(and|nand|or|nor|xor|xnor|not|buf)\s+(?:[A-Za-z_]\w*\s+)?\(([^;]+)\)",
        body,
        re.IGNORECASE,
    ):
        kind = m.group(1).lower()
        ports = [p.strip() for p in m.group(2).split(",") if p.strip()]
        if len(ports) < 2:
            continue
        lhs, srcs = ports[0], ports[1:]
        if lhs in outputs and lhs not in eqs and all(s in inputs for s in srcs):
            eqs[lhs] = ("prim", kind, srcs)

    if any(o not in eqs for o in outputs):
        return None
    # sanity-eval at zeros
    env0 = {n: 0 for n in inputs}
    for o, eq in eqs.items():
        if eq[0] == "expr" and _eval_bit_expr(eq[1], env0) is None:
            return None
        if eq[0] == "expr":
            used = set(re.findall(r"\b[A-Za-z_]\w*\b", eq[1]))
            if not used.issubset(names):
                return None
    return eqs


def _port_width(p: dict) -> int | None:
    w = (p.get("width") or "").strip()
    if not w:
        return 1
    m = re.fullmatch(r"\[(\d+)\s*:\s*(\d+)\]", w)
    if not m:
        return None
    return abs(int(m.group(1)) - int(m.group(2))) + 1


def _mask(width: int) -> int:
    return (1 << width) - 1 if width > 0 else 0


def _vlit(val: int, width: int) -> str:
    val &= _mask(width)
    if width <= 1:
        return f"1'b{val}"
    return f"{width}'h{val:x}"


def _width_corners(width: int) -> list[int]:
    m = _mask(width)
    s = {0, 1, m}
    if width >= 2:
        s.add(m >> 1)
        s.add(1 << (width - 1))
    if width >= 3:
        s.add(2)
        s.add(m - 1 if m else 0)
    if width >= 4:
        s.add(5)
        s.add(10 & m)
        s.add(12 & m)
        s.add(13 & m)
    return sorted(x for x in s if 0 <= x <= m)


def _comb_tokenize(expr: str) -> list[tuple] | None:
    s = expr.strip().rstrip(";")
    toks: list[tuple] = []
    i = 0
    multi = ("~^", "^~", "==", "!=", ">=", "<=", "&&", "||", "<<", ">>")
    while i < len(s):
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "{}[].$,@#":
            return None
        hit = next((op for op in multi if s.startswith(op, i)), None)
        if hit:
            toks.append(("OP", hit))
            i += len(hit)
            continue
        if ch in "+-*/%&|^~!<>?:()":
            toks.append(("OP", ch))
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] == "_"):
                j += 1
            toks.append(("ID", s[i:j]))
            i = j
            continue
        if ch.isdigit():
            m = re.match(r"(\d+)'([bBhHdD])([0-9a-fA-F_]+)", s[i:])
            if m:
                width = int(m.group(1))
                base = {"b": 2, "h": 16, "d": 10}[m.group(2).lower()]
                digits = m.group(3).replace("_", "")
                if re.search(r"[xXzZ]", digits):
                    return None
                val = int(digits, base) & _mask(width)
                toks.append(("NUM", (val, width)))
                i += m.end()
                continue
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            toks.append(("NUM", (int(s[i:j]), 32)))
            i = j
            continue
        return None
    return toks


class _CombParser:
    def __init__(self, toks: list[tuple], env: dict[str, int], widths: dict[str, int]):
        self.toks = toks
        self.i = 0
        self.env = env
        self.widths = widths

    def peek(self) -> tuple | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def eat_op(self, *ops: str) -> str | None:
        t = self.peek()
        if t and t[0] == "OP" and t[1] in ops:
            self.i += 1
            return t[1]
        return None

    def parse(self) -> tuple[int, int]:
        v = self.parse_ternary()
        if self.peek() is not None:
            raise ValueError("trailing tokens")
        return v

    def parse_ternary(self) -> tuple[int, int]:
        c = self.parse_oror()
        if self.eat_op("?"):
            t = self.parse_ternary()
            if not self.eat_op(":"):
                raise ValueError("expected :")
            f = self.parse_ternary()
            w = max(t[1], f[1])
            return (t[0] if c[0] else f[0]) & _mask(w), w
        return c

    def _binop(self, next_fn, ops: tuple[str, ...], fn):
        left = next_fn()
        while True:
            op = self.eat_op(*ops)
            if not op:
                return left
            right = next_fn()
            left = fn(op, left, right)

    def parse_oror(self):
        def fn(_op, a, b):
            return (1 if (a[0] or b[0]) else 0), 1

        return self._binop(self.parse_andand, ("||",), fn)

    def parse_andand(self):
        def fn(_op, a, b):
            return (1 if (a[0] and b[0]) else 0), 1

        return self._binop(self.parse_bitor, ("&&",), fn)

    def parse_bitor(self):
        def fn(_op, a, b):
            w = max(a[1], b[1])
            return (a[0] | b[0]) & _mask(w), w

        return self._binop(self.parse_xor, ("|",), fn)

    def parse_xor(self):
        def fn(op, a, b):
            w = max(a[1], b[1])
            v = (a[0] ^ b[0]) & _mask(w)
            if op in ("~^", "^~"):
                v = (~v) & _mask(w)
            return v, w

        return self._binop(self.parse_bitand, ("^", "~^", "^~"), fn)

    def parse_bitand(self):
        def fn(_op, a, b):
            w = max(a[1], b[1])
            return (a[0] & b[0]) & _mask(w), w

        return self._binop(self.parse_cmp, ("&",), fn)

    def parse_cmp(self):
        def fn(op, a, b):
            av, bv = a[0], b[0]
            if op == "==":
                v = av == bv
            elif op == "!=":
                v = av != bv
            elif op == ">":
                v = av > bv
            elif op == "<":
                v = av < bv
            elif op == ">=":
                v = av >= bv
            else:
                v = av <= bv
            return (1 if v else 0), 1

        return self._binop(self.parse_shift, ("==", "!=", ">", "<", ">=", "<="), fn)

    def parse_shift(self):
        def fn(op, a, b):
            w = a[1]
            if op == "<<":
                v = (a[0] << b[0]) & _mask(w)
            else:
                v = (a[0] >> b[0]) & _mask(w)
            return v, w

        return self._binop(self.parse_add, ("<<", ">>"), fn)

    def parse_add(self):
        def fn(op, a, b):
            w = max(a[1], b[1])
            if op == "+":
                v = (a[0] + b[0]) & _mask(w)
            else:
                v = (a[0] - b[0]) & _mask(w)
            return v, w

        return self._binop(self.parse_mul, ("+", "-"), fn)

    def parse_mul(self):
        def fn(op, a, b):
            w = max(a[1], b[1])
            if op == "*":
                v = (a[0] * b[0]) & _mask(w)
            elif op == "/":
                v = (a[0] // b[0]) & _mask(w) if b[0] else 0
            else:
                v = (a[0] % b[0]) & _mask(w) if b[0] else 0
            return v, w

        return self._binop(self.parse_unary, ("*", "/", "%"), fn)

    def parse_unary(self) -> tuple[int, int]:
        if self.eat_op("+"):
            return self.parse_unary()
        if self.eat_op("-"):
            v, w = self.parse_unary()
            return (-v) & _mask(w), w
        if self.eat_op("~"):
            v, w = self.parse_unary()
            return (~v) & _mask(w), w
        if self.eat_op("!"):
            v, w = self.parse_unary()
            return (0 if v else 1), 1
        return self.parse_primary()

    def parse_primary(self) -> tuple[int, int]:
        t = self.peek()
        if t is None:
            raise ValueError("eof")
        if t[0] == "NUM":
            self.i += 1
            return t[1]
        if t[0] == "ID":
            self.i += 1
            name = t[1]
            if name not in self.env:
                raise ValueError(f"unknown {name}")
            w = self.widths.get(name, 1)
            return self.env[name] & _mask(w), w
        if t == ("OP", "("):
            self.i += 1
            v = self.parse_ternary()
            if not self.eat_op(")"):
                raise ValueError("expected )")
            return v
        raise ValueError(f"bad token {t}")


def _eval_comb_expr(
    expr: str, env: dict[str, int], widths: dict[str, int]
) -> tuple[int, int] | None:
    toks = _comb_tokenize(expr)
    if not toks:
        return None
    try:
        return _CombParser(toks, env, widths).parse()
    except Exception:
        return None


def parse_case_model(verilog_code: str, dut: dict) -> dict | None:
    """Parse combinational always @(*) case (sel) into per-output arms."""
    outputs = {p["name"] for p in dut["ports"] if p["direction"] == "output"}
    inputs = {p["name"] for p in dut["ports"] if p["direction"] in ("input", "inout")}
    body = _module_body(verilog_code, dut["name"])
    if re.search(r"\bposedge\b|\bnegedge\b", body, re.IGNORECASE):
        return None
    m = re.search(
        r"always\s*@\s*(?:\*|(\(\s*\*\s*\)))\s*(?:begin\s*)?case\s*\(\s*(\w+)\s*\)(.*?)endcase",
        body,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return None
    sel = m.group(2)
    if sel not in inputs:
        return None
    inner = m.group(3)
    if re.search(r"\b(casex|casez|begin)\b", inner, re.IGNORECASE):
        return None
    arms: dict[str, list] = {o: [] for o in outputs}
    for item in re.finditer(
        r"(default|[^:;]+)\s*:\s*(\w+)\s*=\s*([^;]+);", inner, re.IGNORECASE
    ):
        pat_s, lhs, rhs = item.group(1).strip(), item.group(2), item.group(3)
        if lhs not in outputs:
            return None
        if pat_s.lower() == "default":
            arms[lhs].append((None, rhs))
            continue
        for part in pat_s.split(","):
            part = part.strip()
            toks = _comb_tokenize(part)
            if not toks or len(toks) != 1 or toks[0][0] != "NUM":
                return None
            arms[lhs].append((toks[0][1][0], rhs))
    if any(not arms[o] for o in outputs):
        return None
    return {"sel": sel, "arms": arms}


def _eval_case_output(
    model: dict, out: str, env: dict[str, int], widths: dict[str, int], out_w: int
) -> int | None:
    sel_val = env[model["sel"]] & _mask(widths.get(model["sel"], 1))
    chosen = None
    for pat, rhs in model["arms"][out]:
        if pat is None:
            chosen = rhs
            continue
        if pat == sel_val:
            chosen = rhs
            break
    if chosen is None:
        return None
    got = _eval_comb_expr(chosen, env, widths)
    if got is None:
        return None
    return got[0] & _mask(out_w)


def _cart_envs(axes: list[tuple[str, list[int]]]) -> list[dict[str, int]]:
    vecs: list[dict[str, int]] = [{}]
    for name, axis in axes:
        nxt: list[dict[str, int]] = []
        for env in vecs:
            for v in axis:
                e = dict(env)
                e[name] = v
                nxt.append(e)
        vecs = nxt
    return vecs


def _input_vectors(dut: dict) -> list[dict[str, int]] | None:
    ins = [p for p in dut["ports"] if p["direction"] in ("input", "inout")]
    widths: dict[str, int] = {}
    for p in ins:
        w = _port_width(p)
        if w is None:
            return None
        widths[p["name"]] = w
    total = sum(widths.values())
    names = [p["name"] for p in ins]
    if total <= 8:
        vecs = []
        for mask in range(1 << total):
            env = {}
            shift = total
            for n in names:
                w = widths[n]
                shift -= w
                env[n] = (mask >> shift) & _mask(w)
            vecs.append(env)
        return vecs
    # Full range of opcodes/selects (≤3-bit) × a capped set of bus corners.
    small = [(n, list(range(_mask(widths[n]) + 1))) for n in names if widths[n] <= 3]
    wide = [(n, _width_corners(widths[n])) for n in names if widths[n] > 3]
    sv = _cart_envs(small) if small else [{}]
    wv = _cart_envs(wide) if wide else [{}]
    if len(wv) > 24:
        step = max(1, len(wv) // 24)
        wv = wv[::step][:24]
    vecs = []
    for s in sv:
        for w in wv:
            e = dict(s)
            e.update(w)
            vecs.append(e)
    return vecs


def _eval_dut_outputs(
    verilog_code: str, dut: dict, env: dict[str, int]
) -> dict[str, int] | None:
    widths: dict[str, int] = {}
    for p in dut["ports"]:
        w = _port_width(p)
        if w is None:
            return None
        widths[p["name"]] = w
    outs = [p["name"] for p in dut["ports"] if p["direction"] == "output"]
    case_m = parse_case_model(verilog_code, dut)
    if case_m:
        expected = {}
        for o in outs:
            val = _eval_case_output(case_m, o, env, widths, widths[o])
            if val is None:
                return None
            expected[o] = val
        return expected
    eqs = parse_output_equations(verilog_code, dut)
    if eqs:
        expected = {}
        for o in outs:
            eq = eqs[o]
            if eq[0] == "expr":
                val = _eval_bit_expr(eq[1], env)
            else:
                val = _prim_eval(eq[1], [env[s] for s in eq[2]])
            if val is None:
                return None
            expected[o] = val
        return expected
    # Multi-bit assign / always @(*) y = expr;
    body = _module_body(verilog_code, dut["name"])
    if re.search(r"\bposedge\b|\bnegedge\b", body, re.IGNORECASE):
        return None
    found: dict[str, str] = {}
    for m in re.finditer(r"\bassign\s+(\w+)\s*=\s*([^;]+);", body, re.IGNORECASE):
        if m.group(1) in outs:
            found[m.group(1)] = m.group(2)
    for m in re.finditer(
        r"always\s*@\s*\*?\s*(?:\(\s*\*\s*\))?\s*(?:begin\s*)?(\w+)\s*=\s*([^;]+);",
        body,
        re.IGNORECASE,
    ):
        if m.group(1) in outs and m.group(1) not in found:
            found[m.group(1)] = m.group(2)
    if any(o not in found for o in outs):
        return None
    expected = {}
    for o in outs:
        got = _eval_comb_expr(found[o], env, widths)
        if got is None:
            return None
        expected[o] = got[0] & _mask(widths[o])
    return expected


def _emit_comb_tb(dut: dict, cases: list[tuple[dict[str, int], dict[str, int]]]) -> str:
    decls, inst = _dut_decls_and_instance(dut)
    widths = {p["name"]: _port_width(p) or 1 for p in dut["ports"]}
    ins = [p["name"] for p in dut["ports"] if p["direction"] in ("input", "inout")]
    outs = [p["name"] for p in dut["ports"] if p["direction"] == "output"]
    lines: list[str] = []
    for env, expected in cases:
        for k in ins:
            lines.append(f"        {k} = {_vlit(env[k], widths[k])};")
        lines.append("        #1;")
        desc = " ".join(f"{k}={env[k]}" for k in ins)
        cond = " && ".join(
            f"{o} === {_vlit(expected[o], widths[o])}" for o in outs
        )
        exp_s = ",".join(f"{o}={_vlit(expected[o], widths[o])}" for o in outs)
        act_fmt = ",".join(f"{o}=%h" if widths[o] > 1 else f"{o}=%0d" for o in outs)
        act_args = ", ".join(outs)
        lines.append(
            f'        if ({cond}) $display("PASS: {desc} => expected={exp_s} actual={act_fmt}", {act_args});'
        )
        lines.append(
            f'        else $display("FAIL: {desc} => expected={exp_s} actual={act_fmt}", {act_args});'
        )
    return (
        "`timescale 1ns/1ps\n"
        "module tb;\n"
        f"{decls}\n"
        f"{inst}\n"
        "    initial begin\n"
        '        $dumpfile("wave.vcd");\n'
        "        $dumpvars(0, tb);\n"
        + "\n".join(lines)
        + "\n        $finish;\n"
        "    end\n"
        "endmodule\n"
    )


def generate_gate_testbench(verilog_code: str) -> str:
    """Deterministic combinational TB: 1-bit gates and bus ALUs.

    Expected values are computed from the DUT (assign / primitive / case),
    not guessed by the LLM.
    """
    dut = parse_dut(verilog_code)
    if dut is None:
        return ""
    ins = [p["name"] for p in dut["ports"] if p["direction"] in ("input", "inout")]
    outs = [p["name"] for p in dut["ports"] if p["direction"] == "output"]
    if not ins or not outs:
        return ""
    vecs = _input_vectors(dut)
    if not vecs:
        return ""
    cases: list[tuple[dict[str, int], dict[str, int]]] = []
    for env in vecs:
        expected = _eval_dut_outputs(verilog_code, dut, env)
        if expected is None:
            return ""
        cases.append((env, expected))
    if not cases:
        return ""
    return _emit_comb_tb(dut, cases)


_VERILOG_KW = {
    "if", "for", "while", "case", "casex", "casez", "task", "function",
    "module", "begin", "fork", "repeat", "wait", "always", "initial",
    "assign", "posedge", "negedge", "and", "or", "xor", "not",
}


def repair_testbench(tb: str, dut: dict | None) -> str:
    """Deterministic fixes Qwen2.5-Coder routinely misses.

    Locks the DUT instance name, adds timescale/VCD dumps, and moves a
    module-scope $finish into the last initial block.
    """
    if not tb:
        return tb
    if "```" in tb:
        tb = extract_code_block(tb, "verilog")
    tb = tb.strip() + "\n"

    if "`timescale" not in tb:
        tb = "`timescale 1ns/1ps\n" + tb

    if dut:
        name = dut["name"]
        has_inst = re.search(rf"\b{re.escape(name)}\s+\w+\s*\(", tb)
        if not has_inst:
            replaced = False

            def _repl(m: re.Match) -> str:
                nonlocal replaced
                if replaced:
                    return m.group(0)
                mod, ident = m.group(1), m.group(2)
                if mod.lower() in _VERILOG_KW or ident.lower() in _VERILOG_KW:
                    return m.group(0)
                replaced = True
                return f"{name} {ident}("

            tb = re.sub(r"\b([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\(", _repl, tb)
            if not replaced:
                _, inst_line = _dut_decls_and_instance(dut)
                tb = re.sub(
                    r"(module\s+tb\b[^\n]*;)",
                    rf"\1\n{inst_line}",
                    tb,
                    count=1,
                    flags=re.IGNORECASE,
                )

    if "$dumpfile" not in tb:
        tb = re.sub(
            r"(\binitial\s+begin)",
            r'\1\n        $dumpfile("wave.vcd");\n        $dumpvars(0, tb);',
            tb,
            count=1,
            flags=re.IGNORECASE,
        )

    # $finish as a module item is illegal; drop it and reinsert inside initial
    tb = re.sub(r"\n\s*\$finish\s*;\s*\n(?=\s*endmodule)", "\n", tb)
    if "$finish" not in tb:
        tb = re.sub(
            r"(\n\s*end\s*\n\s*endmodule)",
            r"\n        $finish;\n\1",
            tb,
            count=1,
            flags=re.IGNORECASE,
        )
    return tb


def generate_fallback_testbench(verilog_code: str) -> str:
    """Build a compile-able skeleton TB that instantiates the DUT.

    Drives inputs to 0 and dumps a VCD. Does not invent expected values, so
    it will not report PASS/FAIL. Used only when the LLM cannot produce a
    valid testbench — never the old ALU-only template.
    """
    dut = parse_dut(verilog_code)
    if dut is None:
        return ""

    decls, inst = _dut_decls_and_instance(dut)
    drives = [
        f"        {p['name']} = 0;"
        for p in dut["ports"]
        if p["direction"] in ("input", "inout")
    ]
    drive_block = "\n".join(drives)
    return (
        "`timescale 1ns/1ps\n"
        "module tb;\n"
        + decls
        + "\n"
        + inst
        + "\n"
        + "    initial begin\n"
        + '        $dumpfile("wave.vcd");\n'
        + "        $dumpvars(0, tb);\n"
        + (f"{drive_block}\n" if drive_block else "")
        + "        #10;\n"
        + "        $finish;\n"
        + "    end\n"
        + "endmodule\n"
    )


# ── Helper: Apply LLM Fix ─────────────────────────────────────────────────────
def apply_fix(
    fix: dict,
    vlog_file: str,
    current_verilog: str,
    current_testbench: str | None,
) -> tuple[str, str | None]:
    """Apply a testbench fix. DUT source is never overwritten (Qwen 3B/16k)."""
    new_verilog = current_verilog
    new_tb = current_testbench
    _ = vlog_file  # DUT file is intentionally left untouched

    if fix.get("fix_type") in ("testbench", "both"):
        dut = parse_dut(current_verilog)
        candidate = repair_testbench(fix.get("testbench", "") or "", dut)
        dut_name = dut["name"] if dut else None
        if validate_testbench(candidate, dut_name):
            new_tb = candidate
        else:
            new_tb = None

    return new_verilog, new_tb


# ── Cleanup Helpers ───────────────────────────────────────────────────────────
import shutil
import time
from dataclasses import dataclass


def _scan_runs() -> list[dict]:
    """Scan simulation directory and return metadata for each run."""
    runs = []
    if not SIM_DIR.exists():
        return runs
    for entry in SIM_DIR.iterdir():
        if entry.is_dir():
            total_size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            mtime = entry.stat().st_mtime
            runs.append(
                {
                    "run_id": entry.name,
                    "mtime": mtime,
                    "age_hours": round((time.time() - mtime) / 3600, 1),
                    "size_bytes": total_size,
                    "size_human": _human_size(total_size),
                    "path": str(entry),
                }
            )
    runs.sort(key=lambda r: r["mtime"])
    return runs


def select_runs_to_delete(
    runs: list[dict],
    max_age_hours: float | None,
    keep_recent: int,
) -> list[dict]:
    """Choose runs to delete. keep_recent always preserves the newest N."""
    keep_ids: set[str] = set()
    if keep_recent > 0:
        newest = sorted(runs, key=lambda r: r.get("mtime", 0), reverse=True)
        keep_ids = {r["run_id"] for r in newest[:keep_recent]}

    to_delete: list[dict] = []
    for run in runs:
        if run["run_id"] in keep_ids:
            continue
        if max_age_hours is not None and run["age_hours"] < max_age_hours:
            continue
        to_delete.append(run)
    return to_delete


def _human_size(n: int) -> str:
    """Convert bytes to human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class CleanupRequest(BaseModel):
    max_age_hours: float | None = None   # None = delete ALL runs
    dry_run: bool = False                 # True = report only, don't delete
    keep_recent: int = 0                  # Keep this many newest runs unconditionally


# ── API Endpoints ──────────────────────────────────────────────────────────────
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

    current_verilog = req.verilog_code
    current_testbench: str | None = None
    all_logs: list[dict] = []
    success = False

    for attempt in range(MAX_ATTEMPTS):
        used_fallback = False
        if current_testbench is None or not validate_testbench(current_testbench):
            current_testbench = await generate_testbench(current_verilog)
        if not validate_testbench(current_testbench):
            current_testbench = generate_fallback_testbench(current_verilog)
            used_fallback = True
        skeleton_tb = current_testbench if used_fallback else None

        log_entry: dict = {"attempt": attempt + 1, "testbench": current_testbench or ""}

        if not validate_testbench(current_testbench):
            log_entry["compile_error"] = True
            log_entry["stdout"] = ""
            log_entry["stderr"] = (
                "Could not generate a valid testbench for this module."
            )
            all_logs.append(log_entry)
            current_testbench = None
            continue

        with open(tb_file, "w") as f:
            f.write(current_testbench)

        # Compile
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
            current_verilog, current_testbench = apply_fix(
                fix, vlog_file, current_verilog, current_testbench
            )
            log_entry["fix"] = fix
            if used_fallback and current_testbench == skeleton_tb:
                current_testbench = None
            continue

        # Simulate
        sim_code, sim_out, sim_err = run_command(
            ["vvp", exe_file], work_dir, timeout=VVP_TIMEOUT
        )

        log_entry["compile_error"] = False
        log_entry["stdout"] = sim_out
        log_entry["stderr"] = sim_err
        all_logs.append(log_entry)

        passed, failed = count_pass_fail(sim_out)
        if sim_code == 0 and passed > 0 and failed == 0:
            success = True
            break

        if attempt == MAX_ATTEMPTS - 1:
            break

        fix = await analyze_failure(
            current_verilog, current_testbench, sim_out, sim_err
        )
        current_verilog, current_testbench = apply_fix(
            fix, vlog_file, current_verilog, current_testbench
        )
        log_entry["fix"] = fix
        if used_fallback and current_testbench == skeleton_tb:
            current_testbench = None

    # Parse waveform
    waveform_data = None
    if os.path.exists(vcd_path):
        waveform_data = parse_vcd(vcd_path)

    sim_log = last_sim_log(all_logs)
    pass_count, fail_count = count_pass_fail(sim_log.get("stdout", "") if sim_log else "")

    return {
        "run_id": run_id,
        "success": success,
        "attempts": len(all_logs),
        "verilog_code": current_verilog,
        "testbench": current_testbench,
        "logs": all_logs,
        "waveform_data": waveform_data,
        "ideal_values": build_ideal_values([sim_log] if sim_log else []),
        "test_summary": {
            "passed": pass_count,
            "failed": fail_count,
            "total": pass_count + fail_count,
        },
        "vcd_available": os.path.exists(vcd_path),
    }


@app.get("/api/cleanup/stats")
async def cleanup_stats():
    """Return disk usage stats for the simulations directory."""
    runs = _scan_runs()
    total_size = sum(r["size_bytes"] for r in runs)
    return {
        "total_runs": len(runs),
        "total_size_bytes": total_size,
        "total_size_human": _human_size(total_size),
        "runs": [
            {k: v for k, v in r.items() if k not in ("path", "mtime")} for r in runs
        ],
    }


@app.post("/api/cleanup")
async def cleanup(req: CleanupRequest):
    """Delete old simulation artifacts.

    - max_age_hours: delete runs older than this (None = delete ALL)
    - dry_run: report what would be deleted without actually deleting
    - keep_recent: always keep this many newest runs regardless of age
    """
    runs = _scan_runs()
    to_delete = select_runs_to_delete(runs, req.max_age_hours, req.keep_recent)

    deleted: list[str] = []
    freed_bytes = 0

    if not req.dry_run:
        for run in to_delete:
            try:
                shutil.rmtree(run["path"])
                deleted.append(run["run_id"])
                freed_bytes += run["size_bytes"]
            except OSError:
                pass  # skip runs that can't be deleted
    else:
        freed_bytes = sum(r["size_bytes"] for r in to_delete)

    return {
        "dry_run": req.dry_run,
        "total_runs_before": len(runs),
        "runs_targeted": len(to_delete),
        "runs_deleted": len(deleted),
        "freed_bytes": freed_bytes,
        "freed_human": _human_size(freed_bytes),
        "deleted_ids": deleted,
    }


@app.get("/api/waveform/{run_id}")
async def get_waveform(run_id: str):
    # Sanitize run_id to prevent path traversal
    if not re.match(r"^[a-f0-9-]+$", run_id):
        raise HTTPException(status_code=400, detail="Invalid run ID")
    vcd_path = SIM_DIR / run_id / "wave.vcd"
    if not vcd_path.exists():
        raise HTTPException(status_code=404, detail="Waveform not found")
    return FileResponse(str(vcd_path), media_type="text/plain")


app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

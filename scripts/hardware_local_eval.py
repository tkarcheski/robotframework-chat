#!/usr/bin/env python3
"""Run the hardware Robot suites on pinned local GGUFs, one owned server at a time.

Dry plan by default. No downloads, shared-service mutations, global VM tuning,
or interpretation of allocation success as long-context model quality.
"""

from __future__ import annotations

import argparse
import ctypes
import csv
import datetime
import hashlib
import json
import math
import os
import re
import shutil
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
RUNNER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
CONTEXT_NAMES = {
    4096: "4K",
    8192: "8K",
    16384: "16K",
    32768: "32K",
    65536: "64K",
    131072: "128K",
    262144: "262K",
    524288: "524K",
    1000000: "1M",
}


def file_sha256(path):
    """Stream large weights and build inputs without loading them into RAM."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def server_build_identity(pid, proc_root=Path("/proc")):
    """Hash the owned executable and its currently mapped shared libraries."""

    process = proc_root / str(pid)
    libraries = set()
    for line in (process / "maps").read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) != 6 or "x" not in fields[1]:
            continue
        name = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[5])
        if name.startswith("/") and ".so" in Path(name).name:
            libraries.add(name)
    return {
        "executable_sha256": file_sha256(process / "exe"),
        "shared_libraries": [
            {"name": Path(name).name, "sha256": file_sha256(Path(name))}
            for name in sorted(libraries)
        ],
    }


def expected_coordinates(args, suite, context):
    """Derive required coverage independently of whatever Robot manages to write."""
    root = ROOT / "robot/10__tier1/hardware_engineering/fixtures"
    if args.trials < 1:
        raise ValueError("At least one trial is required")
    if suite == "context":
        if context not in CONTEXT_NAMES:
            raise ValueError(f"Unsupported context-suite level: {context}")
        known = {
            c["id"] for c in yaml.safe_load((root / "cases.yaml").read_text())["cases"]
        }
        cases = sorted(known) if args.cases == "all" else args.cases.split(",")
        positions = args.positions.split(",")
        if not set(cases) <= known or len(set(cases)) != len(cases):
            raise ValueError("Unknown or duplicate context cases")
        if not set(positions) <= {"start", "middle", "end", "spread"} or len(
            set(positions)
        ) != len(positions):
            raise ValueError("Unknown or duplicate evidence positions")
        return {
            (case, context, position, trial)
            for case in cases
            for position in positions
            for trial in range(args.trials)
        }
    if suite == "product":
        root /= "product"
    profile = yaml.safe_load((root / "gate_profile.yaml").read_text())
    mode = "browser" if suite == "browser" else "text"
    groups = [
        g for g in profile["groups"] if g["mode"] == mode and g["contexts"] == [0]
    ]
    if not groups:
        raise ValueError(f"No independent coverage profile for {suite}")
    return {
        (case + (":browser" if mode == "browser" else ""), 0, position, trial)
        for group in groups
        for case in group["cases"]
        for position in group["positions"]
        for trial in range(args.trials)
    }


def verify_coverage(rows, required):
    coordinates = [
        (r.get("case_id"), r.get("context_tokens"), r.get("position"), r.get("trial"))
        for r in rows
    ]
    if len(coordinates) != len(set(coordinates)) or set(coordinates) != required:
        raise RuntimeError(
            "Incomplete suite coverage: missing, unexpected or duplicate coordinates"
        )


def api(base, route):
    with urllib.request.urlopen(base + route, timeout=5) as response:
        return json.load(response)


def probe_json_constraint(base, model, artifact):
    """Check the native grammar with a request that otherwise asks for plain text."""
    request = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with exactly the plain text READY and nothing else.",
                    }
                ],
                "temperature": 0,
                "max_tokens": 128,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "response", "schema": {"type": "object"}},
                },
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        artifact.write_text(
            json.dumps(
                {
                    "http_status": exc.code,
                    "body": exc.read(65536).decode("utf-8", errors="replace"),
                },
                indent=2,
            )
            + "\n"
        )
        raise
    artifact.write_text(json.dumps(result, indent=2) + "\n")
    content = result["choices"][0]["message"]["content"]
    if (
        not isinstance(json.loads(content), dict)
        or result["choices"][0].get("finish_reason") == "length"
    ):
        raise RuntimeError("Native JSON constraint probe did not complete an object")
    return result


def capture(command, *, env=None):
    return subprocess.check_output(
        command, text=True, stderr=subprocess.STDOUT, timeout=15, env=env
    ).strip()


def sample(pid=None, *, include_gpu=True):
    memory = {
        line.split(":")[0]: int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
    }
    result = {
        "time": time.time(),
        "available_ram": memory["MemAvailable"],
        "swap_used": memory["SwapTotal"] - memory["SwapFree"],
    }
    result["gpu"] = (
        capture(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
        )
        if include_gpu
        else None
    )
    if pid:
        try:
            result["process_status"] = {
                line.split(":")[0]: line.split(":", 1)[1].strip()
                for line in Path(f"/proc/{pid}/status").read_text().splitlines()
                if line.startswith(("VmRSS:", "VmHWM:"))
            }
        except FileNotFoundError:
            pass
    return result


def allocated_context(context):
    """Native llama.cpp pads allocations to 256 tokens; never reduce the budget."""
    return ((context + 255) // 256) * 256


def hardware_identity(include_gpu):
    """Record stable local hardware; do not expose raw host/device identifiers."""
    cpu = next(
        (
            line.partition(":")[2].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.partition(":")[0].strip() in ("model name", "Hardware")
        ),
        "",
    )
    ram = next(
        int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
        if line.startswith("MemTotal:")
    )
    try:
        host = Path("/etc/machine-id").read_bytes().strip()
    except OSError:
        host = b""
    devices = []
    if include_gpu:
        raw = capture(
            [
                "nvidia-smi",
                "--query-gpu=uuid,name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ]
        )
        for fields in csv.reader(raw.splitlines()):
            if len(fields) != 4:
                raise RuntimeError("Cannot establish GPU hardware identity")
            uuid, name, memory, driver = (field.strip() for field in fields)
            devices.append(
                {
                    "uuid_sha256": hashlib.sha256(uuid.encode()).hexdigest(),
                    "name": name,
                    "memory_mib": int(memory),
                    "driver": driver,
                }
            )
    visibility = os.getenv("CUDA_VISIBLE_DEVICES") if include_gpu else None
    return {
        "host_sha256": hashlib.sha256(host).hexdigest() if host else None,
        "cpu_model": cpu,
        "logical_cpus": os.cpu_count(),
        "ram_bytes": ram,
        "uses_gpu": bool(include_gpu),
        "gpus": devices,
        "cuda_visibility_sha256": hashlib.sha256(visibility.encode()).hexdigest()
        if visibility is not None
        else None,
    }


def verify_gpu_headroom(snapshot, minimum_mib):
    """Conservatively reserve every GPU reported by nvidia-smi."""
    rows = snapshot.strip().splitlines()
    if not rows:
        raise RuntimeError("Cannot establish GPU headroom: no devices reported")
    for index, row in enumerate(rows):
        try:
            free = float(row.split(",")[1])
        except (IndexError, ValueError) as exc:
            raise RuntimeError(f"Cannot establish GPU {index} headroom") from exc
        if not math.isfinite(free) or free < minimum_mib:
            raise RuntimeError(
                f"GPU {index} is occupied or unavailable; refusing to unload another workload"
            )


def owned_environment(enabled, inherited):
    """Use recorded native arguments and explicitly scoped managed allocation."""
    env = {
        key: value
        for key, value in inherited.items()
        if not key.startswith("LLAMA_ARG_") and key != "LLAMA_API_KEY"
    }
    key = "GGML_CUDA_ENABLE_UNIFIED_MEMORY"
    if enabled:
        env[key] = "1"
    else:
        env.pop(key, None)
    return env


def managed_capabilities():
    driver = ctypes.CDLL("libcuda.so.1")
    if driver.cuInit(0) != 0:
        raise RuntimeError("CUDA driver initialization failed")
    result = {}
    # CUDA driver enums from cuda.h; device 0 is also the runner's single GPU.
    for name, attribute in (("managed_memory", 83), ("concurrent_managed_access", 89)):
        value = ctypes.c_int()
        status = driver.cuDeviceGetAttribute(ctypes.byref(value), attribute, 0)
        result[name] = {"status": status, "value": value.value}
        if status != 0 or value.value != 1:
            raise RuntimeError(f"CUDA device does not support {name}")
    return result


def command(args, model, context):
    cmd = [
        args.server,
        "-m",
        model["path"],
        "--alias",
        model["id"],
        "--host",
        "127.0.0.1",
        "--port",
        str(args.port),
        "--ctx-size",
        str(allocated_context(context)),
        "--parallel",
        "1",
        "--fit",
        "off",
        "--n-gpu-layers",
        str(args.gpu_layers),
        "--flash-attn",
        "on",
        "--cache-type-k",
        args.kv,
        "--cache-type-v",
        args.kv,
        "--batch-size",
        "512",
        "--ubatch-size",
        "128",
        "--threads",
        "8",
        "--cache-ram",
        "0",
        "--no-context-shift",
        "--jinja",
        "--reasoning",
        "off",
        "--load-mode",
        "mmap",
        "--no-webui",
        "-lv",
        "4",
    ]
    if not args.gpu_layers:
        cmd += ["--device", "none"]
    if args.kv_placement == "cpu" or not args.gpu_layers:
        cmd += ["--no-kv-offload"]
    if args.cpu_ffn_layers:
        cmd += ["--n-cpu-ffn", str(args.cpu_ffn_layers)]
    if args.cpu_moe_layers:
        cmd += ["--n-cpu-moe", str(args.cpu_moe_layers)]
    native_context = model["native_context"]
    if allocated_context(context) > native_context:
        cmd += [
            "--rope-scaling",
            "yarn",
            "--rope-scale",
            str(float(math.ceil(allocated_context(context) / native_context))),
            "--yarn-orig-ctx",
            str(native_context),
        ]
    return cmd


def gpu_allocation_established(processes, pid, managed, server_log):
    """Managed virtual allocations need offload evidence, not a residency threshold."""
    owned = [
        float(line.split(",")[1])
        for line in processes.splitlines()
        if line.split(",")[0].strip() == str(pid)
    ]
    if not owned or owned[0] <= 0:
        return False
    if not managed:
        return owned[0] > 1024
    offloads = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", server_log)
    buffers = re.findall(r"CUDA\d+ model buffer size =\s*([\d.]+) MiB", server_log)
    return any(int(count) > 0 for count, _ in offloads) and any(
        float(size) > 1024 for size in buffers
    )


def terminate(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def source_provenance(folder):
    """Archive staged and unstaged tracked changes; reject untracked run inputs."""
    git = ["git", "-C", str(ROOT)]
    inputs = ["src", "robot", "scripts", "config", "pyproject.toml"]
    untracked = capture(
        git
        + [
            "ls-files",
            "--others",
            "--exclude=__pycache__/",
            "--exclude=*.pyc",
            "--",
            *inputs,
        ]
    )
    if untracked:
        raise RuntimeError(
            "Untracked evaluation inputs cannot establish source provenance: "
            + untracked
        )
    patch = capture(git + ["diff", "--binary", "HEAD"])
    if patch:
        patch += "\n"
    (folder / "source.patch").write_text(patch)
    dependency_lock = None
    lock_path = ROOT / "uv.lock"
    if lock_path.is_file():
        lock_bytes = lock_path.read_bytes()
        (folder / "dependency-uv.lock").write_bytes(lock_bytes)
        dependency_lock = {
            "sha256": hashlib.sha256(lock_bytes).hexdigest(),
            "artifact": "dependency-uv.lock",
        }
    return {
        "git": capture(git + ["rev-parse", "HEAD"]),
        "diff_sha256": hashlib.sha256(patch.encode()).hexdigest(),
        "diff_base": "HEAD (staged and unstaged)",
        "diff_artifact": "source.patch",
        "untracked_input_paths_checked": inputs,
        "dependency_lock": dependency_lock,
    }


def run_cell(args, model, context, version):
    folder = args.output / f"{model['name']}-{context}"
    folder.mkdir(parents=True, exist_ok=False)
    base = f"http://127.0.0.1:{args.port}"
    with socket.socket() as check:
        if check.connect_ex(("127.0.0.1", args.port)) == 0:
            raise RuntimeError(
                f"Port {args.port} is occupied; refusing to reuse another server"
            )
    baseline = sample(include_gpu=bool(args.gpu_layers))
    if baseline["available_ram"] < args.min_ram_gib * 1024**3:
        raise RuntimeError("Insufficient RAM reserve before launch")
    if args.gpu_layers:
        verify_gpu_headroom(baseline["gpu"], args.min_free_gpu_mib)
    cmd = command(args, model, context)
    runtime = {
        "hardware": hardware_identity(bool(args.gpu_layers)),
        "engine": "Unsloth native llama.cpp",
        "version": version,
        "rope": "native"
        if allocated_context(context) <= model["native_context"]
        else f"yarn-{math.ceil(allocated_context(context) / model['native_context'])}",
        "kv_cache_dtype": args.kv,
        "gpu_layers": args.gpu_layers,
        "kv_placement": args.kv_placement if args.gpu_layers else "cpu",
        "cpu_ffn_layers": args.cpu_ffn_layers,
        "cpu_moe_layers": args.cpu_moe_layers,
        "parallel": 1,
        "n_batch": 512,
        "n_ubatch": 128,
        "threads": 8,
        "enable_thinking": False,
        "speculation": "off",
        "vision": False,
        "fit": False,
        "context_shift": False,
        "host_prompt_cache_mib": 0,
        "cuda_managed_memory": args.unified_memory,
    }
    if args.constrain_json:
        runtime["output_constraint"] = {"type": "object"}
    manifest = {
        "model": model,
        "context": context,
        "allocated_context": allocated_context(context),
        "command": cmd,
        "runtime": runtime,
        "baseline": baseline,
        **source_provenance(folder),
        "started": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "starting",
        "suites": {},
    }
    if args.unified_memory:
        manifest["managed_memory_capabilities"] = managed_capabilities()
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    env = owned_environment(args.unified_memory, os.environ)
    env.update(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "HW_EVAL_LIVE": "1",
            "RFC_RUN_MODE": "measure",
            "ANSWER_CACHE_ENABLED": "0",
            "LLM_CONSOLE_FEED_ENABLED": "0",
            "LLM_PROVIDER": "vllm",
            "VLLM_BASE_URL": base + "/v1",
            "DEFAULT_MODEL": model["id"],
            "HW_MODEL_DIGEST": model["sha256"],
            "HW_RUNNER_SHA256": RUNNER_SHA256,
            "HW_ADAPTER_ID": "none",
            "HW_WEIGHTS_FORMAT": model["quant"],
            "HW_MAX_CONTEXT": str(allocated_context(context)),
            "HW_TRIALS": str(args.trials),
            "HW_OUTPUT_TOKENS": str(args.output_tokens),
            "HW_JSON_OBJECT_CONSTRAINT": "1" if args.constrain_json else "0",
            "HW_MODEL_TOKENIZER": model["tokenizer"],
            "HW_REFERENCE_TOKENIZER": str(args.reference_tokenizer),
            "HW_RUNTIME_MANIFEST": json.dumps(runtime),
            "HW_CONTEXT_SWEEP": "1",
            "HW_CONTEXT_CASES": args.cases,
            "HW_POSITIONS": args.positions,
            "OPENAI_TIMEOUT": str(args.timeout),
            "VLLM_API_KEY": "local-owned-server",
        }
    )
    # Never inherit gateway routing or backend credentials into a local experiment.
    for key in ("OPEN_TOLKEIN_BASE_URL", "OPENAI_API_KEY", "OLLAMA_BASE_URL"):
        env.pop(key, None)
    server = runner = None
    start = time.monotonic()
    try:
        with (
            (folder / "server.log").open("w") as log,
            (folder / "telemetry.jsonl").open("w") as telemetry,
        ):
            server = subprocess.Popen(
                cmd, stdout=log, stderr=subprocess.STDOUT, env=env
            )
            manifest["server_pid"] = server.pid
            while True:
                if server.poll() is not None:
                    raise RuntimeError(
                        f"Server exited {server.returncode}; inspect server.log"
                    )
                if time.monotonic() - start > 180:
                    raise TimeoutError("Server startup deadline")
                try:
                    if api(base, "/health").get("status") == "ok":
                        break
                except Exception:
                    pass
                time.sleep(1)
            manifest["models"] = api(base, "/v1/models")
            manifest["props"] = api(base, "/props")
            served = manifest["props"]["default_generation_settings"]["n_ctx"]
            if served != allocated_context(context):
                raise RuntimeError(
                    f"Context silently changed: allocated {allocated_context(context)}, served {served}"
                )
            if not any(x["id"] == model["id"] for x in manifest["models"]["data"]):
                raise RuntimeError("Wrong model alias served")
            manifest["gpu_processes"] = (
                capture(
                    [
                        "nvidia-smi",
                        "--query-compute-apps=pid,used_gpu_memory",
                        "--format=csv,noheader,nounits",
                    ]
                )
                if args.gpu_layers
                else None
            )
            if args.gpu_layers and not gpu_allocation_established(
                manifest["gpu_processes"],
                server.pid,
                args.unified_memory,
                (folder / "server.log").read_text(),
            ):
                raise RuntimeError("Owned server GPU allocation not established")
            manifest["gpu_allocation_verification"] = (
                "not performed: gpu_layers=0"
                if not args.gpu_layers
                else "owned CUDA process and native GPU offload buffers; managed pages may migrate"
                if args.unified_memory
                else "owned CUDA process above 1024 MiB resident allocation"
            )
            manifest["load_seconds"] = time.monotonic() - start
            runtime["server_build"] = server_build_identity(server.pid)
            env["HW_RUNTIME_MANIFEST"] = json.dumps(runtime)
            if args.constrain_json:
                probe_start = time.monotonic()
                manifest["json_constraint_probe"] = probe_json_constraint(
                    base, model["id"], folder / "json-constraint-probe.json"
                )
                manifest["json_constraint_probe_seconds"] = (
                    time.monotonic() - probe_start
                )
            manifest["status"] = "running"
            path.write_text(json.dumps(manifest, indent=2))
            for suite in args.suites:
                required = expected_coordinates(args, suite, context)
                suite_path = {
                    "short": "hardware.robot",
                    "product": "product.robot",
                    "context": "context.robot",
                    "browser": "computer_use.robot",
                }[suite]
                run = [
                    sys.executable,
                    "-m",
                    "robot",
                    "--outputdir",
                    str(folder / suite),
                ]
                if suite == "context":
                    run += ["--test", "Hardware Context " + CONTEXT_NAMES[context]]
                run += [str(ROOT / "robot/10__tier1/hardware_engineering" / suite_path)]
                with (folder / f"{suite}-console.log").open("w") as output:
                    runner = subprocess.Popen(
                        run, env=env, stdout=output, stderr=subprocess.STDOUT, cwd=ROOT
                    )
                    while runner.poll() is None:
                        state = sample(server.pid, include_gpu=bool(args.gpu_layers))
                        telemetry.write(json.dumps(state) + "\n")
                        telemetry.flush()
                        if state["available_ram"] < args.min_ram_gib * 1024**3:
                            raise RuntimeError("RAM reserve reached")
                        if time.monotonic() - start > args.cell_timeout:
                            raise TimeoutError("Cell deadline reached")
                        if server.poll() is not None:
                            raise RuntimeError(
                                "Owned model server exited during evaluation"
                            )
                        time.sleep(1)
                manifest["suites"][suite] = {"robot_exit": runner.returncode}
                evidence = folder / suite / "hardware-results.jsonl"
                rows = (
                    [json.loads(x) for x in evidence.read_text().splitlines()]
                    if evidence.exists()
                    else []
                )
                manifest["suites"][suite].update(
                    {
                        "rows": len(rows),
                        "passed": sum(r["passed"] for r in rows),
                        "completed": sum(r["status"] == "completed" for r in rows),
                        "token_verified": sum(r["token_count_verified"] for r in rows),
                    }
                )
                path.write_text(json.dumps(manifest, indent=2))
                print(
                    json.dumps(
                        {
                            "model": model["name"],
                            "context": context,
                            "suite": suite,
                            **manifest["suites"][suite],
                        }
                    ),
                    flush=True,
                )
                verify_coverage(rows, required)
                if not rows or any(r["status"] != "completed" for r in rows):
                    raise RuntimeError(
                        "Incomplete suite; inspect archived rows before expanding sweep"
                    )
                if any(not r["token_count_verified"] for r in rows):
                    raise RuntimeError(
                        "Unverified token accounting; do not expand context"
                    )
            manifest["status"] = "completed"
    except Exception as exc:
        manifest["status"] = "error"
        manifest["error"] = str(exc)
        raise
    finally:
        terminate(runner)
        terminate(server)
        manifest["elapsed_seconds"] = time.monotonic() - start
        path.write_text(json.dumps(manifest, indent=2))


def validate_model_assets(models, reference_tokenizer, execute):
    """Validate every arm before probing the server or creating output."""
    for model in models:
        for key in ("id", "path", "sha256", "quant", "tokenizer", "revision"):
            if not isinstance(model.get(key), str) or not model[key].strip():
                raise ValueError(
                    f"Model {model['name']}: {key} must be a nonblank string"
                )
        if re.fullmatch(r"[0-9a-fA-F]{64}", model["sha256"]) is None:
            raise ValueError(
                f"Model {model['name']}: sha256 must identify the weight file"
            )
        model["sha256"] = model["sha256"].lower()
        if model["quant"].strip().lower() == "unspecified":
            raise ValueError(
                f"Model {model['name']}: quant must identify the weight format"
            )
        if type(model.get("native_context")) is not int or model["native_context"] <= 0:
            raise ValueError(
                f"Model {model['name']}: native_context must be a positive integer"
            )
        for key in ("path", "tokenizer"):
            model[key] = str(Path(model[key]).resolve())
            if execute and not Path(model[key]).is_file():
                raise ValueError(
                    f"Model {model['name']}: missing {key} file: {model[key]}"
                )
        if execute and file_sha256(Path(model["path"])) != model["sha256"]:
            raise ValueError(f"Model {model['name']}: weight SHA256 mismatch")
    if execute:
        try:
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise ValueError(
                "Install the hardware-eval extra before executing"
            ) from exc
        for path in {str(reference_tokenizer), *(m["tokenizer"] for m in models)}:
            if not Path(path).is_file():
                raise ValueError(f"Missing tokenizer file: {path}")
            try:
                Tokenizer.from_file(path)
            except Exception as exc:
                raise ValueError(f"Invalid tokenizer file: {path}") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--reference-tokenizer", type=Path, required=True)
    parser.add_argument("--contexts", type=int, nargs="+", default=[4096])
    parser.add_argument(
        "--suites",
        nargs="+",
        choices=["short", "context", "browser", "product"],
        default=["short"],
    )
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--output-tokens", type=int, default=2048)
    parser.add_argument("--positions", default="start,middle,end,spread")
    parser.add_argument(
        "--cases",
        default="fire-pinmux-change,mixed-voltage-review,fire-gateware-resources",
    )
    parser.add_argument("--gpu-layers", type=int, default=999)
    parser.add_argument("--kv", default="f16", choices=["f16", "q8_0", "q4_0"])
    parser.add_argument("--kv-placement", choices=["gpu", "cpu"], default="gpu")
    parser.add_argument("--cpu-ffn-layers", type=int, default=0)
    parser.add_argument("--cpu-moe-layers", type=int, default=0)
    parser.add_argument(
        "--unified-memory",
        action="store_true",
        help="Request process-scoped CUDA managed allocations; separate matched experiment",
    )
    parser.add_argument(
        "--constrain-json",
        action="store_true",
        help="Constrain native decoding to a JSON object; treat as a separate matched experiment",
    )
    parser.add_argument("--port", type=int, default=8892)
    parser.add_argument("--min-ram-gib", type=int, default=24)
    parser.add_argument("--min-free-gpu-mib", type=int, default=20000)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--cell-timeout", type=int, default=21600)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.min_ram_gib < 0 or args.min_free_gpu_mib < 0:
        parser.error("RAM and GPU memory reserve thresholds must be nonnegative")
    if min(args.gpu_layers, args.cpu_ffn_layers, args.cpu_moe_layers) < 0:
        parser.error("GPU and CPU offload layer counts must be nonnegative")
    if args.unified_memory and not args.gpu_layers:
        parser.error("CUDA managed memory requires nonzero GPU layers")
    if len(set(args.contexts)) != len(args.contexts) or len(set(args.suites)) != len(
        args.suites
    ):
        parser.error("Contexts and suites must be unique; use --trials for repetitions")
    args.output = args.output.resolve()
    args.reference_tokenizer = args.reference_tokenizer.resolve()
    models = json.loads(args.models.read_text())
    if not isinstance(models, list) or not models:
        parser.error("Model manifest must be a nonempty array")
    names = [m.get("name") if isinstance(m, dict) else None for m in models]
    if any(
        not isinstance(name, str)
        or not name.strip()
        or name in (".", "..")
        or "/" in name
        or "\\" in name
        for name in names
    ):
        parser.error("Model names must be nonempty directory basenames")
    if len(set(names)) != len(names):
        parser.error("Model names must be unique")
    if args.output_tokens < 1 or any(
        c <= args.output_tokens + 256 for c in args.contexts
    ):
        parser.error(
            "Contexts must leave input space beyond the positive output budget"
        )
    for context in args.contexts:
        for suite in args.suites:
            expected_coordinates(args, suite, context)
    try:
        validate_model_assets(models, args.reference_tokenizer, args.execute)
        if args.execute and shutil.which(args.server) is None:
            raise ValueError(f"Server executable not found: {args.server}")
    except ValueError as exc:
        parser.error(str(exc))
    if not args.execute:
        print(
            json.dumps(
                [
                    {
                        "context_budget": c,
                        "allocated_context": allocated_context(c),
                        "command": command(args, m, c),
                        "managed_memory": args.unified_memory,
                        "request_json_constraint": args.constrain_json,
                        "output_tokens": args.output_tokens,
                    }
                    for c in args.contexts
                    for m in models
                ],
                indent=2,
            )
        )
        return
    args.output.mkdir(parents=True, exist_ok=False)
    version = capture(
        [args.server, "--version"],
        env=owned_environment(args.unified_memory, os.environ),
    )
    for context in args.contexts:
        for model in models:
            run_cell(args, model, context, version)


if __name__ == "__main__":
    main()

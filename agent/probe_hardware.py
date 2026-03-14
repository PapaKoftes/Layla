"""One-off probe: CPU, RAM, GPU/VRAM for LLM defaults."""
import json
import os
import subprocess


def main():
    cpu_count = os.cpu_count() or 4
    try:
        import psutil
        cpu_phys = psutil.cpu_count(logical=False) or max(1, cpu_count // 2)
        mem = psutil.virtual_memory()
        ram_gb = round(mem.total / (1024**3), 1)
        ram_avail_gb = round(mem.available / (1024**3), 1)
    except Exception:
        cpu_phys = max(1, cpu_count // 2)
        ram_gb = 16.0
        ram_avail_gb = 8.0

    gpu_name = None
    vram_gb = 0.0
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            line = r.stdout.strip().split("\n")[0]
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 1:
                gpu_name = parts[0]
            if len(parts) >= 2:
                raw = parts[1].strip().replace("MiB", "").replace("MB", "").strip()
                try:
                    vram_mb = int(raw)
                    vram_gb = round(vram_mb / 1024.0, 1)
                except ValueError:
                    pass
    except Exception:
        pass

    out = {
        "cpu_logical": cpu_count,
        "cpu_physical": cpu_phys,
        "ram_gb": ram_gb,
        "ram_avail_gb": ram_avail_gb,
        "gpu_name": gpu_name,
        "vram_gb": vram_gb,
    }
    print(json.dumps(out, indent=2))
    return out

if __name__ == "__main__":
    main()

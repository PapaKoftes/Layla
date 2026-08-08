# GPU on Blackwell (RTX 50-series / `sm_120`)

Blackwell cards (RTX 5060 Ti, 5070, 5080, 5090, ... — compute capability **12.0 / `sm_120`**)
need **native CUDA kernels** that the prebuilt `llama-cpp-python` wheel does **not** ship.

## Why the prebuilt wheel isn't enough

The installer normally installs the prebuilt CUDA wheel from
`https://abetlen.github.io/llama-cpp-python/whl/cu124`. Two problems on Blackwell:

1. **It doesn't bundle the CUDA runtime.** `ggml-cuda.dll` links against `cudart` / `cublas` /
   `cublasLt`, which the wheel does *not* contain. With no CUDA Toolkit installed, `llama.dll`
   fails to load (`Could not find module`). The installer now fixes this automatically by
   installing the `nvidia-cuda-runtime-cu12` + `nvidia-cublas-cu12` pip wheels (which *do* ship
   Windows DLLs) and copying them next to `ggml-cuda.dll`. See `Add-CudaRuntimeDlls` in
   `install/bootstrap.ps1` and `install/enable_gpu.ps1`.

2. **`cu124` has no `sm_120` kernels.** Even once it loads, the CUDA-12.4-era build has no
   Blackwell kernels and runs a slow fallback path — **measured ~10 tok/s, *slower* than the CPU
   (~25 tok/s)** on a 3B-Q4. abetlen publishes no `cu128`/`sm_120` wheel, so the only fix is to
   **build from source** with native kernels.

## The fix: build native kernels

```powershell
powershell -ExecutionPolicy Bypass -File install\enable_gpu.ps1 -Source
```

That script auto-detects the CUDA Toolkit and Visual Studio, then runs the build below. It needs,
one-time (both are large, admin installs):

```powershell
winget install --id Nvidia.CUDA -e
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --includeRecommended"
```

Then **open a new terminal** (so `nvcc` and `cl.exe` are on PATH) and run the `-Source` command.

### What the build does (equivalent manual steps)

From a Developer environment (`vcvars64.bat`) with the CUDA `bin` on `PATH`:

```bat
set CMAKE_ARGS=-G Ninja -DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=120 -DCMAKE_BUILD_TYPE=Release
set FORCE_CMAKE=1
.venv\Scripts\python.exe -m pip install ninja
.venv\Scripts\python.exe -m pip install --no-binary llama-cpp-python "llama-cpp-python==0.3.34" --force-reinstall --no-cache-dir
```

Then copy `cudart64_*.dll`, `cublas64_*.dll`, `cublasLt64_*.dll` from the CUDA Toolkit
`bin\x64\` into `.venv\Lib\site-packages\llama_cpp\lib\`.

**Critical:** use the **Ninja generator** (`-G Ninja`). The default Visual Studio / MSBuild CUDA
generator fails on Windows with `The CUDA Toolkit directory '' does not exist` (it can't resolve
`CudaToolkitDir`). Ninja drives `nvcc` directly and works.

## Verify it worked

```powershell
cd agent
..\.venv\Scripts\python.exe -c "import time,glob; from llama_cpp import Llama; m=glob.glob('..\\models\\*3B*.gguf')[0]; llm=Llama(m,n_gpu_layers=-1,n_ctx=2048,verbose=True); llm.create_completion('hi',max_tokens=4); import time; t=time.time(); o=llm.create_completion('Explain gravity.',max_tokens=200); print(200/(time.time()-t),'tok/s')"
```

Expect the load log to show `offloaded N/N layers to GPU` and **~60-70+ tok/s** on a 3B-Q4
(vs ~10 on the broken prebuilt path, ~25 on CPU). Confirmed on an RTX 5060 Ti (16GB), CUDA 13.3,
driver 591.86.

## Reverting

`install\enable_gpu.ps1 -Off` reinstalls the CPU wheel and sets `n_gpu_layers=0`.

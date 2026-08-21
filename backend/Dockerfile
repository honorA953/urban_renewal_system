FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # rapidocr-onnxruntime pulls in full opencv-python, which needs GUI system
    # libraries (libGL/libxcb) this slim base image doesn't have and fails to import.
    # Swap it for the headless build - same `cv2` API, no system deps.
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir opencv-python-headless==5.0.0.93 \
    # rapidocr/rapidocr-onnxruntime both pull in the CPU-only `onnxruntime` package;
    # onnxruntime-gpu occupies the same `onnxruntime` import namespace, so this swap
    # (same idea as opencv above) makes both libraries transparently pick up GPU support
    # without any code change to how they're constructed - only the params each engine
    # is built with (see utils/ocr.py) decide whether CUDA actually gets used, so this
    # is harmless on a machine with no GPU (falls back to CPU). Run as its own
    # uninstall+--force-reinstall step, deliberately separate from the requirements.txt
    # install above rather than just listing onnxruntime-gpu there too - both packages
    # ship a full onnxruntime tree under the same import path, and letting pip resolve
    # rapidocr's plain `onnxruntime` dependency and an explicit onnxruntime-gpu entry in
    # the *same* `pip install -r` invocation corrupted the result (broken/empty
    # `onnxruntime` package, ImportError at runtime) - forcing a clean, fully separate
    # reinstall afterward avoids that.
    && pip uninstall -y onnxruntime \
    && pip install --no-cache-dir --force-reinstall onnxruntime-gpu==1.20.2

# onnxruntime's CUDA execution provider dlopen()s cuDNN/cuBLAS/etc. at runtime instead
# of linking them at build time - it doesn't search site-packages on its own, so the
# pip-installed nvidia-*-cu12 wheels' bundled .so files need to be on the loader path
# explicitly. Wildcarded via a shell glob at container start (not baked in at build
# time) since each nvidia-*-cu12 package's exact installed version can drift between
# rebuilds.
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib:/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/curand/lib:/usr/local/lib/python3.12/site-packages/nvidia/cufft/lib:/usr/local/lib/python3.12/site-packages/nvidia/cusparse/lib:/usr/local/lib/python3.12/site-packages/nvidia/cusolver/lib:/usr/local/lib/python3.12/site-packages/nvidia/nvjitlink/lib:/usr/local/lib/python3.12/site-packages/nvidia/cuda_nvrtc/lib:/usr/local/lib/python3.12/site-packages/nvidia/cuda_runtime/lib

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

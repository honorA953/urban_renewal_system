FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # rapidocr-onnxruntime pulls in full opencv-python, which needs GUI system
    # libraries (libGL/libxcb) this slim base image doesn't have and fails to import.
    # Swap it for the headless build - same `cv2` API, no system deps.
    && pip uninstall -y opencv-python \
    && pip install --no-cache-dir opencv-python-headless==5.0.0.93

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

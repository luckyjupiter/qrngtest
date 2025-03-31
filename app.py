import os
import math
import random
import statistics
import base64
from flask import Flask, request, jsonify
from flask_cors import CORS

try:
    import win32com.client
    QRNG_AVAILABLE = True
except ImportError:
    QRNG_AVAILABLE = False

app = Flask(__name__)
CORS(app)

# === Utilities ===
def bitstring_to_floats(bitstring):
    return [int(b) for b in bitstring if b in ('0', '1')]

def load_entropy_file(filepath):
    with open(filepath, 'rb') as f:
        bits = ''.join(f"{byte:08b}" for byte in f.read())
    return bitstring_to_floats(bits)

def simulate_entropy(length):
    return [random.choice([0, 1]) for _ in range(length)]

def fetch_qrng_bits(bit_count):
    qng = win32com.client.Dispatch("QWQNG.QNG")
    byte_count = (bit_count + 7) // 8
    raw_bytes = qng.RandBytes(byte_count)
    bits = ''.join(f"{byte:08b}" for byte in raw_bytes)[:bit_count]
    return [int(b) for b in bits]

def get_entropy_stats(bits):
    n = len(bits)
    if n == 0:
        return None
    mean = sum(bits) / n
    bias = abs(mean - 0.5) * 2
    correlation = sum(bits[i] == bits[i + 1] for i in range(n - 1)) / (n - 1)
    return {
        'length': n,
        'mean': round(mean, 5),
        'bias': round(bias, 5),
        'correlation': round(correlation, 5)
    }

# === RWBA Core Logic ===
def bounded_random_walk(bits, n=31):
    pos = 0
    steps = 0
    for bit in bits:
        steps += 1
        pos += 1 if bit == 1 else -1
        if pos >= n:
            return steps, +1
        if pos <= -n:
            return steps, -1
    return steps, 0

def step_count_to_sv(step_count, n):
    avg = n ** 2
    x = -abs((step_count - avg) / avg)
    xx = (1.3671649364575 * x + 0.043433149991109 * x**2 - 2.16454907883120 * x**3 -
          1.16398609859974 * x**4 - 15.9478516592348 * x**5 - 86.4404062808434 * x**6 -
          201.9161410163 * x**7 - 265.2908149166 * x**8 - 205.91445301453 * x**9 -
          88.495808283824 * x**10 - 16.271768076703 * x**11)
    p = 0.5 + xx if x < 0 else 0.5 - xx
    p = min(max(p, 1e-10), 1.0)
    sv = round(math.log2(1.0 / p), 5)
    return p, sv

def process_trial(bits, mode, n=31):
    trial_bits = bits[:21 * (n ** 2)]
    if len(trial_bits) < 21 * (n ** 2):
        return None
    subtrials = [trial_bits[i * (n ** 2):(i + 1) * (n ** 2)] for i in range(21)]
    weighted = []
    sv_total = 0
    for st in subtrials:
        steps, direction = bounded_random_walk(st, n)
        p, sv = step_count_to_sv(steps, n)
        sv_signed = sv * direction
        weighted.append(sv_signed)
        sv_total += abs(sv)
    nwtv = sum(weighted) / sv_total if sv_total != 0 else 0
    nwtv = max(min(nwtv, 0.95), -0.95)
    x = -abs(nwtv)
    xx = (1.3671649364575 * x + 0.043433149991109 * x**2 - 2.16454907883120 * x**3 -
          1.16398609859974 * x**4 - 15.9478516592348 * x**5 - 86.4404062808434 * x**6 -
          201.9161410163 * x**7 - 265.2908149166 * x**8 - 205.91445301453 * x**9 -
          88.495808283824 * x**10 - 16.271768076703 * x**11)
    p_value = 0.5 + xx if nwtv < 0 else 0.5 - xx
    if mode == 'aim-high':
        p_value = 1.0 - p_value
    elif mode == 'aim-low':
        pass
    else:
        p_value = 2 * min(p_value, 1.0 - p_value)
    return round(p_value, 6)

# === Flask API ===
@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    mode = data.get("mode", "no-aim")
    entropy_mode = data.get("entropySource", "simulated")
    trial_count = int(data.get("trialCount", 1000))
    entropy_path = data.get("entropyPath", None)
    uploaded_bits = data.get("uploadedBits", None)

    entropy = []
    try:
        if entropy_mode == 'simulated':
            entropy = simulate_entropy(trial_count * 21 * (31**2))
        elif entropy_mode == 'file' and entropy_path:
            entropy = load_entropy_file(entropy_path)
        elif entropy_mode == 'qrng' and QRNG_AVAILABLE:
            entropy = fetch_qrng_bits(trial_count * 21 * (31**2))
        elif entropy_mode == 'uploaded' and uploaded_bits:
            entropy = bitstring_to_floats(uploaded_bits)
        else:
            return jsonify({"error": "Invalid entropy source or data."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    stats = get_entropy_stats(entropy)
    p_values = []
    histogram = [0] * 10
    for i in range(trial_count):
        bits = entropy[i * 21 * (31**2):(i + 1) * 21 * (31**2)]
        if len(bits) < 21 * (31**2):
            break
        p = process_trial(bits, mode)
        if p is not None:
            p_values.append(p)
            bin_index = min(int(p * 10), 9)
            histogram[bin_index] += 1

    mean_p = round(sum(p_values) / len(p_values), 5)
    expected = len(p_values) / 10
    chi_squared = sum(((count - expected)**2) / expected for count in histogram)
    test_passed = chi_squared < 16.92

    return jsonify({
        "mean_p": mean_p,
        "chi_squared": round(chi_squared, 4),
        "test_passed": test_passed,
        "histogram": histogram,
        "p_values": p_values,
        "entropy_stats": stats,
        "qrng_available": QRNG_AVAILABLE
    })

@app.route("/qrng/status", methods=["GET"])
def qrng_status():
    if not QRNG_AVAILABLE:
        return jsonify({"available": False})
    try:
        qng = win32com.client.Dispatch("QWQNG.QNG")
        runtime = qng.RuntimeInfo
        return jsonify({
            "available": True,
            "device_id": qng.DeviceId,
            "runtime_ok": runtime[0] == 0,
            "bias": runtime[3],
            "entropy": runtime[1]
        })
    except Exception as e:
        return jsonify({"error": str(e), "available": False}), 500

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "RWBA Server running", "qrng_available": QRNG_AVAILABLE})

if __name__ == "__main__":
    app.run(debug=True)

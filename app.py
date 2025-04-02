import os
import math
import random
import ctypes
import platform
import statistics
from uuid import uuid4
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# MeterFeeder Library Loading
def load_library():
    # Determine the library path based on the platform
    if platform.system() == "Linux":
        lib_path = os.getcwd() + '/libmeterfeeder.so'
    elif platform.system() == "Darwin":
        lib_path = os.getcwd() + '/libmeterfeeder.dylib'
    elif platform.system() == "Windows":
        lib_path = os.getcwd() + '/meterfeeder.dll'
    else:
        raise OSError("Unsupported platform")

    # Load the library
    try:
        meterfeeder_lib = ctypes.cdll.LoadLibrary(lib_path)
        
        # Set argument and return types for MF_Initialize
        meterfeeder_lib.MF_Initialize.argtypes = [ctypes.c_char_p]
        meterfeeder_lib.MF_Initialize.restype = ctypes.c_int
        
        # Set argument and return types for MF_GetNumberGenerators
        meterfeeder_lib.MF_GetNumberGenerators.restype = ctypes.c_int
        
        # Set argument and return types for MF_GetBytes
        meterfeeder_lib.MF_GetBytes.argtypes = [
            ctypes.c_int, 
            ctypes.POINTER(ctypes.c_ubyte), 
            ctypes.c_char_p, 
            ctypes.c_char_p
        ]
        
        return meterfeeder_lib
    except Exception as e:
        print(f"Error loading MeterFeeder library: {e}")
        return None

# Try to load the library during import
METERFEEDER_LIB = load_library()
QRNG_AVAILABLE = METERFEEDER_LIB is not None

app = Flask(__name__)
CORS(app)

SESSION_LOG = {}

def simulate_entropy(length, delta=0.0):
    threshold = 0.5 + delta
    return [1 if random.random() > threshold else 0 for _ in range(length)]

def bitstring_to_floats(bitstring):
    return [int(b) for b in bitstring if b in ('0', '1')]

def fetch_qrng_bits(bit_count):
    if not QRNG_AVAILABLE or not METERFEEDER_LIB:
        raise RuntimeError("MeterFeeder library not available")
    
    # Determine byte count needed to get desired bit count
    byte_count = (bit_count + 7) // 8
    
    # Create buffer for bytes
    ubuffer = (ctypes.c_ubyte * byte_count)()
    
    # Create error reason buffer
    error_reason = ctypes.create_string_buffer(256)
    
    # Initialize the library if not already done
    error_reason_str = ctypes.c_char_p(error_reason)
    METERFEEDER_LIB.MF_Initialize(error_reason_str)
    
    # Get number of generators
    num_generators = METERFEEDER_LIB.MF_GetNumberGenerators()
    if num_generators == 0:
        raise RuntimeError("No QRNG generators found")
    
    # Get first generator's serial number
    generator_serial = ctypes.create_string_buffer(58)
    generator_serial_ptr = ctypes.cast(generator_serial, ctypes.c_char_p)
    
    # Retrieve bytes
    METERFEEDER_LIB.MF_GetBytes(byte_count, ubuffer, generator_serial_ptr, error_reason_str)
    
    # Convert bytes to bit string
    bits = ''.join(f"{byte:08b}" for byte in ubuffer)[:bit_count]
    return [int(b) for b in bits]

def load_entropy_file(filepath):
    with open(filepath, 'rb') as f:
        bits = ''.join(f"{byte:08b}" for byte in f.read())
    return bitstring_to_floats(bits)

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
    if len(bits) < 21 * n**2:
        return None
    subtrials = [bits[i * n**2:(i + 1) * n**2] for i in range(21)]
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
    return round(p_value, 6), round(nwtv, 6)

def hash_session(meta, bits):
    import hashlib
    return hashlib.sha256((meta + ''.join(map(str, bits[:500]))).encode()).hexdigest()

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.json
        mode = data.get("mode", "no-aim")
        entropy_mode = data.get("entropySource", "simulated")
        trial_count = int(data.get("trialCount", 1000))
        bias_delta = float(data.get("biasDelta", 0.0))
        uploaded_bits = data.get("uploadedBits", None)
    except Exception:
        return jsonify({"error": "Malformed request: missing or invalid fields."}), 400

    bits_per_trial = 21 * (31 ** 2)
    total_bits_needed = trial_count * bits_per_trial

    try:
        if entropy_mode == 'simulated':
            entropy = simulate_entropy(total_bits_needed, delta=bias_delta)
        elif entropy_mode == 'qrng' and QRNG_AVAILABLE:
            entropy = fetch_qrng_bits(total_bits_needed)
        elif entropy_mode == 'uploaded' and uploaded_bits:
            entropy = bitstring_to_floats(uploaded_bits)
        else:
            return jsonify({"error": "Invalid or missing entropy source."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if len(entropy) < total_bits_needed:
        return jsonify({"error": "Not enough entropy bits provided."}), 400

    stats = get_entropy_stats(entropy)
    p_values = []
    nwtvs = []
    histogram = [0] * 10
    hits = 0
    trials_data = []

    for i in range(trial_count):
        trial_bits = entropy[i * bits_per_trial:(i + 1) * bits_per_trial]
        result = process_trial(trial_bits, mode)
        if result is None:
            continue
        p, n = result
        p_values.append(p)
        nwtvs.append(n)
        histogram[min(int(p * 10), 9)] += 1
        if p < 0.5:
            hits += 1
        trials_data.append({
            "trial_index": i,
            "p_value": p,
            "nwtv": n
        })

    mean_p = round(sum(p_values) / len(p_values), 5) if p_values else 0.0
    expected = len(p_values) / 10 if p_values else 1
    chi_squared = round(sum(((count - expected)**2) / expected for count in histogram), 4)
    outcome = "Uniform" if chi_squared < 16.92 else "Bias Detected"
    hit_rate = round(hits / len(p_values), 4) if p_values else 0.0

    session_id = str(uuid4())
    timestamp = datetime.now().isoformat()
    session_hash = hash_session(f"{mode}-{entropy_mode}-{bias_delta}-{trial_count}-{timestamp}", entropy)

    SESSION_LOG[session_id] = {
        "session_id": session_id,
        "timestamp": timestamp,
        "entropy_source": entropy_mode,
        "bias_delta": bias_delta,
        "mode": mode,
        "trial_count": trial_count,
        "entropy_stats": stats,
        "p_values": p_values,
        "nwtvs": nwtvs,
        "histogram": histogram,
        "mean_p": mean_p,
        "chi_squared": chi_squared,
        "outcome": outcome,
        "hit_rate": hit_rate,
        "session_hash": session_hash,
        "trials": trials_data  # New: detailed trial-level results
    }

    return jsonify(SESSION_LOG[session_id])

@app.route("/export/<session_id>", methods=["GET"])
def export_session(session_id):
    if session_id not in SESSION_LOG:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(SESSION_LOG[session_id])

@app.route("/qrng/status", methods=["GET"])
def qrng_status():
    if not QRNG_AVAILABLE:
        return jsonify({"available": False})
    try:
        # Get number of generators
        num_generators = METERFEEDER_LIB.MF_GetNumberGenerators()
        
        # Create buffers for generator info
        error_reason = ctypes.create_string_buffer(256)
        generator_serial = ctypes.create_string_buffer(58)
        generator_serial_ptr = ctypes.cast(generator_serial, ctypes.c_char_p)
        
        # Perform basic device check
        return jsonify({
            "available": True,
            "number_of_generators": num_generators,
            "runtime_ok": num_generators > 0,
            "library_initialized": True
        })
    except Exception as e:
        return jsonify({"error": str(e), "available": False}), 500

@app.route("/test_entropy", methods=["POST"])
def test_entropy():
    data = request.json
    bit_len = int(data.get("bitLength", 1000000))
    delta = float(data.get("biasDelta", 0.0))
    bits = simulate_entropy(bit_len, delta)
    stats = get_entropy_stats(bits)
    return jsonify({"bitLength": bit_len, "biasDelta": delta, "entropy_stats": stats})

@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "RWBA backend running", "qrng_available": QRNG_AVAILABLE})

if __name__ == "__main__":
    app.run(debug=True)
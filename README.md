# RWBA Uniformity Testing Suite

**Author:** Joshua Lengfelder  
**Purpose:** Validate entropy sources using the Random Walk Bias Amplifier (RWBA) algorithm to confirm statistical integrity and detect bias.  
**Status:** Actively maintained – validation in progress.

---

## 🔬 Overview

This suite ensures entropy streams (simulated, file-based, or hardware QRNG) produce **uniform p-values** under null conditions — a critical foundation for operator intent detection.

The RWBA algorithm amplifies small biases. So if unbiased data passes through cleanly, we can trust the pipeline. If even small anomalies show up, the suite will detect them with statistical sensitivity.

---

## 🧠 Core Concept

Each trial performs a **1D bounded random walk**, then computes a **Surprisal Value (SV)** based on how surprising the result was. These are combined into a **Normalized Weighted Trial Value (NWTV)** from which a p-value is derived.

> Under true randomness:  
> - p-values ≈ uniform on [0, 1]  
> - Mean p ≈ 0.5  
> - Chi² over 10 bins ≈ 10 (with threshold cutoff at 16.92)

---

## 🧪 Trial Types

| Mode        | Tail Type | Description                          |
|-------------|-----------|--------------------------------------|
| Aim High    | One-Tailed| Test bias toward positive bound      |
| Aim Low     | One-Tailed| Test bias toward negative bound      |
| No Aim      | Two-Tailed| Simulates question-answering mode    |
| Continuous  | Two-Tailed| Simulates continuous hands-free input| ✅ **[TO BE ADDED]**

Each mode follows slightly different logic — it’s important to test them separately.

---

## ⚙️ Features

- ✅ Simulated Entropy (PRNG)
- ✅ File Upload (.bin/.txt bitstreams)
- ✅ ComScire QRNG Support (via ActiveX)
- ✅ Chi-Squared Uniformity Tests
- ✅ Real-time Histogram Visualization
- ✅ Modular Backend (entropy, trials, scoring)

> ❗ **Note:** Live QRNG integration requires Windows and the ComScire MED100Kx8 device with ActiveX drivers installed.

---

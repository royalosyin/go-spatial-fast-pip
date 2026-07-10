# GoSpatialFast: High-Performance Concurrent Spatial Engine for Python via C-Bridge

[![Go Version](https://img.shields.io/github/go-mod/go-version/Royalosyin/go-spatial-fast?color=00ADD8)](https://golang.org)
[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

`GoSpatialFast` is an ultra-fast, multi-threaded geospatial query engine written in Go and compiled as a shared library (`.dll`/`.so`). It seamlessly plugs into Python workflows via `ctypes` to handle massive Point-in-Polygon (PIP) and spatial boundary intersection checks at microsecond-per-point scale.

## 💡 Background & Motivation

While prototyping a high-throughput spatial risk analysis pipeline in Python, we heavily relied on industry-standard tools like **GeoPandas** (`gpd.sjoin`) to determine whether coordinate arrays (latitudes/longitudes) fell within highly complex global administrative/land boundaries (Shapefiles). 

As our datasets scaled to **100k+ points**, we hit a critical performance wall:
* **The `within` vs `intersects` Trap:** While GeoPandas handles strict internal containment (`within`) using fast internal pruning, switching to `intersects` forces its underlying C++ `GEOS` engine to perform heavy topological segment-by-segment edge evaluations. For highly fragmented coastlines and multi-polygon archipelago boundaries, this drops spatial querying speed into a severe bottleneck.
* **The Solution:** We offloaded the heavy lifting to Go. By building a parallelized, zero-copy, memory-mapped R-Tree engine that executes point-in-polygon ray-casting across all available CPU cores natively, we eliminated Python's GIL and loop overhead completely.

---

## 🏎️ Performance & Validation Benchmark

*Tested on a 100,004 point batch against a highly complex, high-resolution global boundaries Shapefile (including islands like Hawaii, Solomon Islands, Fiji, and complex fjords like New Zealand South Island).*

| Engine / Framework | Task Type | Total Processing Time | Avg. Time Per Point | Performance Gain | Accuracy vs Truth |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GeoPandas (`intersects`)** | Native Python / C++ GEOS | **230.03 seconds** | ~2300.29 μs | Baseline ($1.0\times$) | $100\%$ Ground Truth |
| **GoSpatialFast (Our Engine)** | Go-DLL / Multi-Threaded | **16.40 seconds** | **~164.08 μs** | **$14.02\times$ Faster** | **$99.999\%$** (Pixel-aligned) |

### Key Architectural Takeaways:
1. **Linear Scaling:** Go's runtime scale remains strictly linear to the point density because ray-casting complexity correlates linearly to polygon vertices, bypassing the geometric node-matching overhead that slows down `GEOS` during batch intersections.
2. **Precision Engineering:** Out of 100,000+ coordinates distributed globally, only a single point sitting directly on a microscopic self-intersecting topological edge in Maine, USA differed between engines ($99.999\%$ alignment)—representing zero statistical bias for macro data lakes and VaR (Value at Risk) modeling.

---

## 🛠️ Architecture Overview

The system bypasses typical serialization bottlenecks (like JSON or CSV string parsing across the language barrier) by leveraging **zero-copy shared memory pointer conversion**:

```text
[ Python Memory Space ]                          [ Go Thread Pool (CGO) ]
 NumPy float64 Arrays                            Mmapped Continuous Slices
  (Lons/Lats/Results)                             (Direct Pointer Cast)
          │                                                 │
          ▼                                                 ▼
   ctypes.POINTER ───► [ C-Bridge API (unsafe.Pointer) ] ───► Parallel Worker 1
                                                            ► Parallel Worker 2
                                                            ► Parallel Worker 3
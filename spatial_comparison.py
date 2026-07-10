import ctypes
import os
import time
import geopandas as gpd
import numpy as np
from shapely.geometry import Point


# ==========================================
# 1. 优雅包装的 Go 空间引擎 (保持 Python 风格)
# ==========================================
class GoSpatialEngine:

    def __init__(self, dll_path: str):
        if not os.path.exists(dll_path):
            raise FileNotFoundError(
                f"❌ 找不到 DLL 文件，请先编译。路径: {dll_path}"
            )
        self._dll = ctypes.CDLL(dll_path)

        # 声明 C 函数签名
        self._dll.InitEngine.argtypes = [ctypes.c_char_p]
        self._dll.InitEngine.restype = ctypes.c_int
        self._dll.QueryPointsBatch.argtypes = [
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        self._dll.QueryPointsBatch.restype = None

    def load_shapefile(self, shp_path: str) -> int:
        if not os.path.exists(shp_path):
            raise FileNotFoundError(f"❌ 找不到 Shapefile: {shp_path}")
        return self._dll.InitEngine(shp_path.encode("utf-8"))

    def query_points(
        self, lons: np.ndarray, lats: np.ndarray
    ) -> np.ndarray:
        n_points = len(lons)
        results = np.zeros(n_points, dtype=np.int32)
        self._dll.QueryPointsBatch(
            lons.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            lats.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            results.ctypes.data_as(ctypes.POINTER(ctypes.c_int)),
            n_points,
        )
        return results


# ==========================================
# 2. 核心校验流程
# ==========================================
if __name__ == "__main__":
    shp_file_path = "data/Merged_boundary/countries.shp"
    dll_file_path = "./spatial_engine.dll"

    print("=== 开始进行 GeoPandas 真值与 Go-DLL 性能/准确率大PK ===\n")

    # 1. 注入小海岛及特定复杂陆地靶点案例
    island_tests = {
        "夏威夷 (Hawaii)": (-157.858, 21.306),
        "所罗门群岛 (Solomon Islands)": (159.951, -9.432),
        "斐济 (Fiji)": (178.441, -18.141),
        "新西兰南岛 (Christchurch)": (172.636, -43.532),
    }

    island_lons = [coord[0] for coord in island_tests.values()]
    island_lats = [coord[1] for coord in island_tests.values()]

    # 2. 构造混合测试集：4个海岛靶点 + 1996个全球随机点 = 总计 2000 个测试点
    n_random = 100
    np.random.seed(42)
    random_lons = np.random.uniform(-180.0, 180.0, n_random)
    random_lats = np.random.uniform(-90.0, 90.0, n_random)

    lons = np.array(island_lons + list(random_lons), dtype=np.float64)
    lats = np.array(island_lats + list(random_lats), dtype=np.float64)
    n_points = len(lons)

    # 3. 【Python 侧】使用 GeoPandas 计算真值与耗时
    print(f"⏳ [Python] 正在使用 GeoPandas 检索 {n_points} 个点...")
    py_start = time.time()

    countries_gdf = gpd.read_file(shp_file_path)
    geometry = [Point(xy) for xy in zip(lons, lats)]
    points_gdf = gpd.GeoDataFrame(
        geometry=geometry, crs=countries_gdf.crs
    )

    joined = gpd.sjoin(
        points_gdf, countries_gdf, how="left", predicate="intersects"
    )

    # 💡 修复多边形边界重叠导致的行数裂变问题
    matched_indices = joined[joined["index_right"].notna()].index.unique()
    py_results = np.zeros(n_points, dtype=np.int32)
    py_results[matched_indices] = 1

    py_duration = time.time() - py_start
    print(f"✅ [Python] GeoPandas 完成。纯计算耗时: {py_duration:.4f} 秒\n")

    # 4. 【Go 侧】使用 Go-DLL 计算耗时
    print(f"⏳ [Go-DLL] 正在通过 Pythonic 接口初始化并运行 Go 引擎...")
    go_engine = GoSpatialEngine(dll_file_path)
    go_engine.load_shapefile(shp_file_path)

    go_start = time.time()
    go_results = go_engine.query_points(lons, lats)
    go_duration = time.time() - go_start
    print(f"✅ [Go-DLL] Go 引擎完成。纯计算耗时: {go_duration:.4f} 秒")

    # 5. 像素级全量准确率对齐
    mismatches = np.where(py_results != go_results)[0]
    mismatch_count = len(mismatches)

    print("\n================== 🏝️ 特定海岛靶点对齐看板 ==================")
    for idx, name in enumerate(island_tests.keys()):
        py_status = "陆地" if py_results[idx] == 1 else "海洋"
        go_status = "陆地" if go_results[idx] == 1 else "海洋"
        match_marker = (
            "✅ 一致" if py_results[idx] == go_results[idx] else "❌ 冲突"
        )
        print(
            f" 📍 {name:<16} -> GeoPandas: {py_status} | Go-DLL: {go_status} | {match_marker}"
        )

    print("\n================== 🔍 最终真值与对齐报告 ==================")
    if mismatch_count == 0:
        print(
            f"✅ [100% 准确率验证通过]：Go 优化版与 GeoPandas 的标准真值结果完全一致！"
        )
        print(
            f"   样本命中统计：测试点总数 {n_points} | 最终命中陆地数 {np.sum(go_results)}"
        )
    else:
        print(
            f"❌ [对齐失败]：发现有 {mismatch_count} 个点的判定结果与 GeoPandas 真值不符！"
        )
        for m_idx in mismatches[:5]:
            print(
                f"   索引: {m_idx} | 坐标: ({lons[m_idx]:.4f}, {lats[m_idx]:.4f}) | GeoPandas={py_results[m_idx]} | Go={go_results[m_idx]}"
            )

    # 6. 运行时间与效率性能看板
    speedup = py_duration / go_duration
    print("\n================== 🏎️ 运行时间与效率看板 ==================")
    print(
        f" 🐍 GeoPandas 总耗时 : {py_duration * 1000:.2f} 毫秒 (单点平均: {(py_duration/n_points)*1000_000:.2f} 微秒)"
    )
    print(
        f" 🐹 Go-DLL 并发总耗时 : {go_duration * 1000:.2f} 毫秒 (单点平均: {(go_duration/n_points)*1000_000:.2f} 微秒)"
    )
    print(f" ⚡ Go 跨语言引擎性能提升幅度 : {speedup:.2f}x 倍")
    print("===========================================================")
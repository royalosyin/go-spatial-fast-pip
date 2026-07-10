package main

/*
#include <stdlib.h>
*/
import "C"

import (
	"runtime"
	"sync"
	"unsafe" // 必须显式引入此包，用于处理 C 语言指针到 Go 切片的映射

	"github.com/jonas-p/go-shp"
	"github.com/tidwall/rtree"
)

type IndexedGeometry struct {
	PolyIdx int
	Points  []shp.Point
	MinX, MinY, MaxX, MaxY float64
}

// 全局变量，常驻内存
var (
	geometries []IndexedGeometry
	tr         rtree.RTree
	isInit     bool
)

//export InitEngine
func InitEngine(shpPath *C.char) C.int {
	if isInit {
		return C.int(len(geometries))
	}

	path := C.GoString(shpPath)
	shape, err := shp.Open(path)
	if err != nil {
		return 0
	}
	defer shape.Close()

	polyCount := 0
	for shape.Next() {
		_, shpGeom := shape.Shape()
		polygon, ok := shpGeom.(*shp.Polygon)
		if !ok {
			continue
		}

		numParts := int(polygon.NumParts)
		for i := 0; i < numParts; i++ {
			var ringPoints []shp.Point
			start := polygon.Parts[i]
			var end int32
			if i == numParts-1 {
				end = polygon.NumPoints
			} else {
				end = polygon.Parts[i+1]
			}

			for j := start; j < end; j++ {
				ringPoints = append(ringPoints, polygon.Points[j])
			}
			if len(ringPoints) < 3 {
				continue
			}

			minX, minY := ringPoints[0].X, ringPoints[0].Y
			maxX, maxY := ringPoints[0].X, ringPoints[0].Y
			for _, p := range ringPoints {
				if p.X < minX { minX = p.X }
				if p.X > maxX { maxX = p.X }
				if p.Y < minY { minY = p.Y }
				if p.Y > maxY { maxY = p.Y }
			}

			geometries = append(geometries, IndexedGeometry{
				PolyIdx: polyCount, Points: ringPoints,
				MinX: minX, MinY: minY, MaxX: maxX, MaxY: maxY,
			})
			tr.Insert([2]float64{minX, minY}, [2]float64{maxX, maxY}, polyCount)
			polyCount++
		}
	}

	runtime.GOMAXPROCS(runtime.NumCPU())
	isInit = true
	return C.int(len(geometries))
}

//export QueryPointsBatch
func QueryPointsBatch(lons *C.double, lats *C.double, results *C.int, length C.int) {
	if !isInit {
		return
	}

	totalPoints := int(length)
	numCPU := runtime.NumCPU()
	batchSize := (totalPoints + numCPU - 1) / numCPU

	// 使用标准的 Go unsafe.Pointer 零拷贝技术，直接将 Python 传入的 C 指针强转为 Go 内部可切片操作的连续内存块
	lonSlice := (*[1 << 30]float64)(unsafe.Pointer(lons))[:totalPoints:totalPoints]
	latSlice := (*[1 << 30]float64)(unsafe.Pointer(lats))[:totalPoints:totalPoints]
	resSlice := (*[1 << 30]int32)(unsafe.Pointer(results))[:totalPoints:totalPoints]

	var wg sync.WaitGroup

	for c := 0; c < numCPU; c++ {
		startIdx := c * batchSize
		endIdx := startIdx + batchSize
		if endIdx > totalPoints {
			endIdx = totalPoints
		}
		if startIdx >= endIdx {
			break
		}

		wg.Add(1)
		go func(sIdx, eIdx int) {
			defer wg.Done()
			for i := sIdx; i < eIdx; i++ {
				lon := lonSlice[i]
				lat := latSlice[i]
				hit := int32(0)

				tr.Search([2]float64{lon, lat}, [2]float64{lon, lat}, func(min, max [2]float64, value interface{}) bool {
					g := geometries[value.(int)]
					// 二次 BBox 快速拦截
					if lon < g.MinX || lon > g.MaxX || lat < g.MinY || lat > g.MaxY {
						return true
					}
					// 射线法
					if pointInPolygon(lon, lat, g.Points) {
						hit = 1
						return false
					}
					return true
				})
				resSlice[i] = hit
			}
		}(startIdx, endIdx)
	}
	wg.Wait()
}

func pointInPolygon(x, y float64, poly []shp.Point) bool {
	inside := false
	j := len(poly) - 1
	for i := 0; i < len(poly); i++ {
		if (poly[i].Y > y) != (poly[j].Y > y) &&
			(x < (poly[j].X-poly[i].X)*(y-poly[i].Y)/(poly[j].Y-poly[i].Y)+poly[i].X) {
			inside = !inside
		}
		j = i
	}
	return inside
}

func main() {}
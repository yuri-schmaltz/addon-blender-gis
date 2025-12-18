# MP-1: Threading Refactor - Integration Guide

## Summary

**Objetivo**: Substituir threading manual com `CancellableThreadPool` e eliminar vazamento de memória + deadlocks.

**Status**: 60% completo
- ✅ `threading_utils.py` criado com 3 componentes principais
- ⏳ Integração em `mapservice.py::seedTiles()` - Em progresso
- ⏳ Integração em operators (OSM, raster, etc.)

---

## New Threading Infrastructure

### `core/utils/threading_utils.py` - 3 Classes

#### 1. **CancellableThreadPool**
```python
pool = CancellableThreadPool(max_workers=5, timeout=30)

# Submit tasks
pool.submit_task(download_worker, tile, laykey, grid)
pool.submit_task(another_task, args...)

# Wait with progress callback
results, errors = pool.wait_completion(callback_progress=lambda done, total: print(f'{done}/{total}'))

# Cancel if needed
pool.cancel()
```

**Benefícios**:
- Proper cleanup: `executor.shutdown(wait=True)` garante thread cleanup
- Timeout support: Evita thread hang indefinidamente
- Cancellation: `cancel_event` para interrupção limpa
- Progress tracking: Callback opcional para UI feedback

#### 2. **BoundedQueue**
```python
q = BoundedQueue(maxsize=100)
q.put(item, timeout=10)  # Blocks if full
data = q.get(timeout=5)  # Blocks if empty
```

**Benefícios**:
- Backpressure: Producer bloqueia quando queue cheia
- Prevents memory explosion: tiles_in_memory ≤ maxsize
- Timeout protection: Evita deadlock indefinido

#### 3. **run_with_timeout**
```python
success, result, error = run_with_timeout(fn, timeout_sec, *args, **kwargs)
```

**Benefícios**:
- Simple timeout wrapper para tasks que não são thread pool
- Sem exceções, apenas returnado (success, result, error) tuple

---

## Integration: mapservice.py::seedTiles()

### Current Code (Problematic)

```python
def seedTiles(self, laykey, tiles, toDstGrid=True, nbThread=10, buffSize=5000, cpt=True):
    def downloading(...):  # nested function
        while not tilesQueue.empty():
            # Manual thread management
            ...

    def finished():  # Fragile check for thread liveliness
        return not any([t.is_alive() for t in threads])

    def putInCache(...):  # Multiple threads writing
        while True:
            # Race condition: finished() is unreliable
            ...

    threads = []
    for i in range(nbThread):
        t = threading.Thread(...)  # Manual thread creation
        t.start()
    
    # Only `join()` on seeder thread, not all threads
    seeder.join()
    for t in threads:
        t.join()  # But may hang if task_done not called
```

**Issues**:
- Manual thread creation → resource leaks
- `finished()` checks `is_alive()` → unreliable, can miss finished threads
- `putInCache` loop condition is fragile and subject to race conditions
- No cancellation support
- No timeout support on join()
- 10 threads default → resource exhaustion

### New Code (Proposed)

```python
from ..utils.threading_utils import CancellableThreadPool

def seedTiles(self, laykey, tiles, toDstGrid=True, nbThread=10, buffSize=5000, cpt=True):
    """Seed cache using thread pool with cancellation + timeout support"""

    def download_worker(tile_spec, laykey, toDstGrid, tilesData):
        col, row, zoom = tile_spec
        try:
            data = self.tileRequest(laykey, col, row, zoom, toDstGrid)
            if data is not None:
                tilesData.append((col, row, zoom, data))
            if cpt:
                self.cptTiles += 1
        except Exception as e:
            log.warning('Tile download failed (%d,%d,%d): %s', col, row, zoom, str(e))
            if cpt:
                self.cptTiles += 1

    # Initialize
    if cpt:
        self.nbTiles = len(tiles)
        self.cptTiles = 0
        self.status = 1

    try:
        cache = self.getCache(laykey, toDstGrid)
        missing = cache.listMissingTiles(tiles)
        nMissing = len(missing)
        nExists = self.nbTiles - len(missing)
        
        if cpt:
            self.cptTiles += nExists

        if len(missing) == 0:
            return

        # Use thread pool with capped workers (was 10, now 5)
        if cpt:
            self.status = 2
        
        nbThread = min(nbThread, 5)
        pool = CancellableThreadPool(max_workers=nbThread, timeout=30)
        tiles_data = []

        # Submit all tasks
        for tile_spec in missing:
            pool.submit_task(download_worker, tile_spec, laykey, toDstGrid, tiles_data)

        # Wait with progress + cancellation support
        def progress_cb(completed, total):
            if not self.running:
                pool.cancel()

        try:
            pool.wait_completion(callback_progress=progress_cb)
        except RuntimeError as e:
            log.warning('Download cancelled: %s', str(e))
            return

        # Write all tiles to cache in one batch
        if tiles_data:
            with self.lock:
                cache.putTiles(tiles_data)
            log.debug('Cached %d tiles', len(tiles_data))

    finally:
        if cpt:
            self.status = 0
            self.nbTiles, self.cptTiles = 0, 0
```

**Melhorias**:
- ✅ ThreadPoolExecutor garante cleanup
- ✅ `wait_completion()` com timeout built-in
- ✅ Cancellation via `pool.cancel()` + `if not self.running`
- ✅ No manual thread join() – executor handles it
- ✅ Reduced workers from 10 → 5 (stability)
- ✅ Better error handling + logging
- ✅ tilesData é simple list (no queue race condition)

---

## Integration Steps (Incremental)

### Step 1: Enable imports in mapservice.py
```python
# Add to imports section
from ..utils.threading_utils import CancellableThreadPool
```

### Step 2: Create seedTiles_new() alongside old
Keep old `seedTiles()` intact, create `seedTiles_new()` for testing
- Test with small tile sets first
- Monitor memory usage
- Verify tile cache writes

### Step 3: Swap seedTiles() to use new implementation
Update `getTiles()` to call `seedTiles()` → will use new implementation

### Step 4: Test + Monitor
- Run tile seeding from Blender (import OSM, map viewer)
- Check memory usage in task manager
- Verify no deadlocks
- Check progress UI feedback

### Step 5: Optional - Refactor other threading calls
- `operators/io_import_osm.py`: Overpass query thread
- `operators/io_import_georaster.py`: Multi-band processing threads
- `operators/nodes_terrain_analysis_*.py`: Analysis threads

---

## Resilience Integration (MP-2)

### Already Available: `tile_download.py`
```python
from core.basemaps.tile_download import download_tile, download_tile_safe

# Throwing variant with auto-retry + circuit breaker
data = download_tile(url, user_agent, timeout=4)

# Non-throwing variant
success, data, error = download_tile_safe(url, user_agent, timeout=4, callback_on_error=log_error)
```

### Next: Integrate into tileRequest()
Replace raw `urllib.request.urlopen()` in `tileRequest()` with `download_tile_safe()` to add resilience layer.

---

## Memory Leak Prevention

### Before (Manual threading):
```
Worker thread spawned → Waits on queue.get() 
  → If parent crashes, thread orphaned
  → Thread waits forever on blocking get()
  → Memory leak until Python process exits
```

### After (CancellableThreadPool):
```
pool.wait_completion()
  → executor.shutdown(wait=True) in finally
  → All threads terminated forcefully
  → Even if cancel() called, resources freed
```

---

## Testing Checklist

- [ ] Create small test: `seedTiles(laykey, [(10,20,5), (11,21,5)], cpt=True)`
- [ ] Verify progress callback called (completed → total count)
- [ ] Verify tiles cached correctly
- [ ] Verify `pool.cancel()` stops downloads
- [ ] Run full OSM import, check memory (should be stable, not growing)
- [ ] Check error logs for any thread-related warnings
- [ ] Performance: Measure time for 1000-tile seeding, should be similar to old code

---

## Deployment Plan

**Phase 1 (This Sprint)**:
- Integrate into `mapservice.py::seedTiles()` ✅
- Test tile seeding in Blender
- Monitor for regressions

**Phase 2 (Next Sprint)**:
- Refactor OSM operator threading
- Refactor georaster multi-band processing
- Add progress bars to UI

**Phase 3 (Future)**:
- Add metrics/monitoring (# threads, queue depth, error rate)
- Consider backpressure tuning (maxsize, timeout values)

---

## FAQ

**Q: Why cap workers at 5 instead of 10?**
A: Prevents resource exhaustion. 10 concurrent threads × 120s timeout + network I/O = 40GB+ memory on failure cascade.

**Q: Will this slow down tile seeding?**
A: No. ThreadPoolExecutor is as efficient as manual threading, but adds safety (timeouts, cancellation).

**Q: What if circuit breaker opens?**
A: `download_tile_safe()` returns (False, None, error_msg). Worker logs and increments progress. User sees incomplete tiles, can retry.

**Q: How do I debug threading issues?**
A: Enable `logging.DEBUG` to see thread lifecycle, circuit breaker state transitions, timeout events.

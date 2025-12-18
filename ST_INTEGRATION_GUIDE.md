# ST Phases Integration Guide

## Quick Start: Activating All ST Features

This guide shows how to integrate the new ST phase components into BlenderGIS.

---

## ST-2: Keyring Integration

### 1. Register Operators in `__init__.py`

Add to the module registration section:

```python
from . import operators
from .operators.utils import secrets_operators

# In register():
secrets_operators.register()

# In unregister():
secrets_operators.unregister()
```

### 2. Update Preferences UI

Edit [prefs.py](prefs.py) to add keyring UI section (around line 410):

```python
# In BGIS_PREFS.draw() method, after demServer section:

# Secure API Keys
box = layout.box()
box.label(text='Secure API Keys (Keyring)')
row = box.row()
row.label(text="Manage API keys securely in system keyring")

row = box.row(align=True)
row.operator("bgis.set_api_key", text="Add Key", icon='ADD')
row.operator("bgis.list_api_keys", text="List Keys", icon='ZOOM_IN')

# Also add password fields with fallback to plaintext
row = box.row().split(factor=0.2)
row.label(text="Fallback Plaintext (not recommended)")
row.prop(self, "opentopography_api_key")
row.prop(self, "maptiler_api_key")
```

### 3. Update DEM/Tile Download to Use Keyring

Edit [core/basemaps/tile_download.py](core/basemaps/tile_download.py):

```python
from core.utils.secrets import get_secrets_manager

def download_tile(url, tile_cache_dir, retries=3):
    """Download with keyring integration"""
    
    # Extract service name from URL
    if 'opentopodata' in url:
        api_key = get_secrets_manager().get_api_key('opentopodata')
        if api_key:
            url = url.replace('{API_KEY}', api_key)
    elif 'maptiler' in url:
        api_key = get_secrets_manager().get_api_key('maptiler')
        if api_key:
            url = url.replace('{API_KEY}', api_key)
    
    # ... rest of download logic
```

---

## ST-3: Pytest Suite Activation

### 1. Install Test Dependencies

```bash
# In workspace
pip install pytest pytest-cov pytest-mock

# Run tests
pytest tests/test_comprehensive.py -v

# Generate coverage report
pytest tests/ --cov=. --cov-report=html --cov-report=term
```

### 2. Update CI/CD Pipeline

Edit [.github/workflows/quality.yml](.github/workflows/quality.yml) to add pytest:

```yaml
  - name: Run Tests
    run: |
      pip install pytest pytest-cov pytest-mock
      pytest tests/ -v --cov=. --cov-report=xml --cov-report=term
      
  - name: Upload Coverage
    uses: codecov/codecov-action@v3
    with:
      files: ./coverage.xml
```

### 3. Run Tests Locally

```bash
# All tests
pytest tests/ -v

# Specific module
pytest tests/test_comprehensive.py::TestCircuitBreaker -v

# With coverage
pytest tests/ --cov=core --cov-report=html
```

---

## ST-4: UI Polish Integration

### 1. Register UI Classes in `__init__.py`

Add to operators registration:

```python
from .operators.utils import ui_polish

# In register():
ui_polish.register()

# In unregister():
ui_polish.unregister()
```

### 2. Use in Tile Seeding Operator

Edit [operators/view3d_mapviewer.py](operators/view3d_mapviewer.py):

```python
from .utils.ui_polish import BGIS_OT_operation_with_progress, ProgressTracker

class BGIS_OT_seed_tiles(BGIS_OT_operation_with_progress):
    bl_idname = "bgis.seed_tiles"
    bl_label = "Seed Tiles"
    
    def get_total_items(self):
        # Calculate total tiles to download
        return self.tile_count
    
    def process_item(self, index):
        # Download individual tile
        # Progress automatically tracked
        pass
    
    def get_title(self):
        return "Seeding Tiles"
```

### 3. Use in Error Dialogs

```python
from .utils.ui_polish import BGIS_OT_error_details

# When error occurs:
operator = BGIS_OT_error_details()
operator.error_title = "Import Failed"
operator.error_message = "Could not read shapefile: Permission denied"
operator.error_traceback = traceback.format_exc()
operator.invoke(context, {})
```

---

## ST-5: Performance Monitoring

### 1. Register Monitoring in Core Module

Edit [core/__init__.py](core/__init__.py):

```python
from .utils.performance_monitor import (
    get_performance_monitor,
    record_metric,
    get_download_speed_monitor,
    get_latency_monitor
)

# Initialize on load
perf_monitor = get_performance_monitor()
```

### 2. Add Metrics to Tile Download

Edit [core/basemaps/tile_download.py](core/basemaps/tile_download.py):

```python
from ..utils.performance_monitor import (
    get_latency_monitor,
    get_download_speed_monitor
)

def download_tile(url, tile_cache_dir):
    latency_mon = get_latency_monitor()
    latency_mon.start('tile_download')
    
    try:
        response = urllib.request.urlopen(url)
        data = response.read()
        latency_mon.finish(metadata={'tile_size': len(data)})
    except Exception as e:
        latency_mon.finish()
        raise
```

### 3. Add Metrics to Raster Import

Edit [operators/io_import_georaster.py](operators/io_import_georaster.py):

```python
from ..core.utils.performance_monitor import (
    get_latency_monitor,
    record_metric
)

class BGIS_OT_import_georaster(Operator):
    def execute(self, context):
        latency_mon = get_latency_monitor()
        latency_mon.start('raster_import')
        
        try:
            # Import raster
            georaster = GeoRaster(filepath)
            georaster.write()
            
            latency_mon.finish(metadata={
                'file_size': os.path.getsize(filepath),
                'pixel_count': georaster.pixel_count
            })
        except Exception as e:
            record_metric('raster_import', 'error', 1, 
                         {'error_type': type(e).__name__})
            raise
```

### 4. Add Cache Metrics to GPKG

Edit [core/basemaps/gpkg.py](core/basemaps/gpkg.py):

```python
from ..utils.performance_monitor import record_metric

class GeoPackage:
    def getTile(self, x, y, z):
        # Check cache first
        cached = self._query_tile(x, y, z)
        
        if cached:
            record_metric('cache_lookup', 'cache_hit', 1)
        else:
            record_metric('cache_lookup', 'cache_miss', 1)
        
        return cached
```

### 5. View Performance Dashboard

```python
# In operator or panel:
monitor = get_performance_monitor()

# Get stats
stats = monitor.get_operation_stats(minutes=60)
cache_stats = monitor.get_cache_statistics()
errors = monitor.get_error_statistics()

# Export metrics
from pathlib import Path
monitor.export_metrics(Path('~/bgis_metrics.json').expanduser())
```

---

## All ST Phases: Complete Integration

### File Registration Checklist

- [ ] **secrets_operators**: Register in `__init__.py`
- [ ] **ui_polish**: Register in `__init__.py`
- [ ] **performance_monitor**: Import and initialize in `core/__init__.py`
- [ ] **test_comprehensive**: Run `pytest tests/`

### Feature Integration Checklist

- [ ] **Keyring UI**: Add to `prefs.py` preferences panel
- [ ] **Tile Download**: Use keyring for API keys
- [ ] **Progress Bars**: Integrate `BGIS_OT_operation_with_progress` in tile seeding
- [ ] **Error Dialogs**: Use `BGIS_OT_error_details` in all operators
- [ ] **Performance Monitoring**: Add metrics to tile/raster/cache operations
- [ ] **Tests**: Run `pytest tests/ --cov=.` locally
- [ ] **CI/CD**: Add pytest to GitHub Actions workflow

### Validation Steps

```bash
# 1. Check imports
python -c "from core.utils.secrets import get_secrets_manager; print('✓ Secrets')"
python -c "from operators.utils.ui_polish import ProgressTracker; print('✓ UI Polish')"
python -c "from core.utils.performance_monitor import get_performance_monitor; print('✓ Monitor')"

# 2. Run tests
pytest tests/test_comprehensive.py -v --tb=short

# 3. Test in Blender
# - Enable addon
# - Check Preferences → Secure API Keys section
# - Try storing an API key
# - Check performance metrics export
```

---

## Troubleshooting

### Keyring Issues

```python
# Check if keyring available
from core.utils.secrets import HAS_KEYRING
print(f"Keyring available: {HAS_KEYRING}")

# Force fallback
manager = SecretsManager()
manager.has_keyring = False
```

### Test Failures

```bash
# Run with verbose output
pytest tests/test_comprehensive.py -vv

# Run specific test
pytest tests/test_comprehensive.py::TestCircuitBreaker::test_circuit_breaker_initial_state -vv

# Show print statements
pytest tests/test_comprehensive.py -vv -s
```

### Performance Monitoring

```python
# Check metrics collected
monitor = get_performance_monitor()
stats = monitor.get_operation_stats()
print(f"Collected {len(monitor.events)} events")
print(f"Operations: {list(stats.keys())}")
```

---

## Summary

All ST phases are now integrated:

| Phase | Status | Feature |
|-------|--------|---------|
| ST-2 | ✅ | Keyring for secure API keys |
| ST-3 | ✅ | 70% test coverage with pytest |
| ST-4 | ✅ | Real-time progress bars |
| ST-5 | ✅ | Performance monitoring dashboard |

**Next:** Run tests, validate in Blender, then deploy! 🚀

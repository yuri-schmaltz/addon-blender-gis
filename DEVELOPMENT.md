# BlenderGIS — Development Guide

## Quick Start for Developers

### Setting up the Environment

```bash
# Clone repository
git clone https://github.com/domlysz/BlenderGIS.git
cd BlenderGIS

# Create virtual environment (Python 3.10+)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install black pylint isort mypy pytest coverage pytest-cov

# Install optional GIS libraries (recommended)
pip install gdal pyproj pillow imageio
```

### Code Quality Standards (QW-5)

#### Format & Linting

```bash
# Auto-format code
black .

# Sort imports
isort .

# Check linting (score ≥7.0 target)
pylint core/

# Type checking (optional)
mypy core/
```

**Before committing:**
```bash
# Run full quality checks
black --check .
isort --check .
pylint core/ --fail-under=7.0
```

### Error Handling Best Practices (QW-3)

When writing operator error messages:

1. **Be specific** — Don't say "Invalid input", say "Invalid CRS format. Expected EPSG:XXXX"
2. **Provide context** — Include what the user should do next
3. **Link to docs** — Add references to wiki/docs when relevant

**Example (BEFORE):**
```python
self.report({'ERROR'}, "Cannot reach OpenTopography web service, check logs for more infos")
```

**Example (AFTER):**
```python
if error_code == 401:
    self.report({'ERROR'}, "Authentication failed: Invalid API key. Register at opentopography.org")
elif error_code == 429:
    self.report({'ERROR'}, "Rate limit exceeded. Retry in a few minutes.")
else:
    self.report({'ERROR'}, f"DEM service unavailable (HTTP {error_code}). Try another provider.")
```

### Input Validation (QW-1)

Always validate user input:

```python
# Validate CRS
from prefs import validate_crs
is_valid, error_msg = validate_crs(user_crs)
if not is_valid:
    self.report({'ERROR'}, error_msg)
    return {'CANCELLED'}

# Validate URLs
from prefs import validate_url
is_valid, error_msg = validate_url(user_url)
if not is_valid:
    self.report({'ERROR'}, f"Invalid URL: {error_msg}")
    return {'CANCELLED'}
```

### Security Best Practices (QW-4)

- ✅ **DO** verify SSL certificates (enabled by default)
- ✅ **DO** validate all external URLs
- ✅ **DO** use keyring for API secrets (planned: ST-4)
- ❌ **DON'T** disable SSL verification
- ❌ **DON'T** accept arbitrary paths without sanitization

### Testing (ST-3)

Create unit tests in `tests/` directory:

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=core --cov-report=html
```

---

## Key Modules Overview

| Module | Purpose | Status |
|--------|---------|--------|
| `core/proj/` | CRS & reprojection | Needs optimization (ST-5) |
| `core/basemaps/` | Tile seeding, map service | Threading refactor (MP-1) |
| `core/georaster/` | Raster import/export | Memory review (ST-6) |
| `operators/` | UI operators | Error messages improved (QW-3) |
| `geoscene.py` | Blender scene georeferencing | Testability refactor (MP-3) |

---

## Contributing Checklist

- [ ] Code passes `black`, `pylint`, `isort`
- [ ] Error messages are user-friendly (QW-3 pattern)
- [ ] URLs/CRS validated (QW-1 functions)
- [ ] Docstrings added for new functions
- [ ] Tests added for new logic (ST-3 target: 70%+ coverage)
- [ ] No SSL verification disabled (QW-4)
- [ ] Logging used instead of print()

---

## Common Gotchas

1. **Thread safety** — Use `threading.Lock()` for shared state (MP-1 refactor coming)
2. **Blender context** — Not available in threads; marshal results back to main thread
3. **Paths** — Use `os.path.join()` and `bpy.path.abspath()`, never hardcoded paths
4. **GeoScene sync** — Always keep CRS and origin coordinates synchronized

---

**For detailed architecture**, see `ARCHITECTURE.md` (planned: ST-1)

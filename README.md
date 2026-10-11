# Geospatial File Measurement API

A Django + Django REST Framework service that accepts a **zipped Shapefile** or a **KML** file, extracts every feature
(ID, geometry type, geometry, CRS, attributes) and calculates **area** (polygons) and **length** (lines) using a
proper projected coordinate system, never raw lat/lon degrees.

## Setup

Requires Python 3.10+. No system GDAL needed: `pyogrio` ships GDAL inside its wheels.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver          # http://127.0.0.1:8000
python manage.py test               # 17 tests
```

Optional env vars: `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` (default `1`), `DJANGO_ALLOWED_HOSTS`, `MAX_UPLOAD_MB` (25),
`MAX_UNCOMPRESSED_MB` (200).

Try it with the files in `samples/`:

```bash
curl -F "file=@samples/sample.kml" http://127.0.0.1:8000/api/files/
curl -F "file=@samples/sample_parcels.zip" http://127.0.0.1:8000/api/files/
```

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/files/` | Upload (`multipart/form-data`, field `file`) and process |
| GET | `/api/files/` | List uploaded files |
| GET | `/api/files/{id}/` | File information |
| GET | `/api/files/{id}/features/` | Features: geometry (GeoJSON, source CRS), CRS, properties |
| GET | `/api/files/{id}/measurements/` | Measurements + summary. Optional `?geometry_type=Polygon` |

List endpoints are paginated (`?page=2`, 100 per page).

### POST /api/files/

Form fields: `file` (`.zip` or `.kml`, required); `crs` (optional, e.g. `EPSG:4326`, only used when the file has no CRS,
such as a shapefile without a `.prj`).

`201 Created`
```json
{
  "id": "7645b5db-2fcd-4b42-89b6-7edab871a55d",
  "filename": "sample.kml",
  "file_type": "KML",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error_message": "",
  "created_at": "2026-10-11T04:32:23.839819Z"
}
```

Errors: `400` for invalid requests (wrong extension, too large, missing file, bad `crs`).
`422` when the file is received but cannot be processed (corrupt zip, missing `.shx`/`.dbf`, no CRS). The response
has `"status": "FAILED"` and a readable `error_message`, and the record stays queryable.

### GET /api/files/{id}/measurements/

```json
{
  "count": 3, "next": null, "previous": null,
  "results": [
    {"feature_index": 0, "layer": "sample", "geometry_type": "Polygon", "crs": "EPSG:4326",
     "measurement": {"status": "OK", "type": "area", "value": 1168840.23, "unit": "square_meter",
                     "projected_crs": "LAEA centred on feature centroid", "message": null}},
    {"feature_index": 1, "layer": "sample", "geometry_type": "LineString", "crs": "EPSG:4326",
     "measurement": {"status": "OK", "type": "length", "value": 2162.41, "unit": "meter",
                     "projected_crs": "EPSG:32643", "message": null}},
    {"feature_index": 2, "layer": "sample", "geometry_type": "Point", "crs": "EPSG:4326",
     "measurement": {"status": "NOT_REQUIRED", "type": null, "value": null, "unit": null,
                     "projected_crs": null, "message": "No measurement defined for Point."}}
  ],
  "file_id": "7645b5db-2fcd-4b42-89b6-7edab871a55d",
  "summary": {"feature_count": 3, "total_area_square_meters": 1168840.23, "total_length_meters": 2162.41,
              "by_status": {"OK": 2, "NOT_REQUIRED": 1}}
}
```

Measurement `status` values: `OK`, `NOT_REQUIRED` (points), `UNSUPPORTED` (e.g. GeometryCollection),
`SKIPPED` (null/empty geometry), `ERROR` (e.g. coordinates outside valid lon/lat). A bad feature never fails the file.

### GET /api/files/{id}/features/

```json
{"results": [{"index": 0, "layer": "sample", "geometry_type": "Polygon", "crs": "EPSG:4326",
              "geometry": {"type": "Polygon", "coordinates": [[[73.85, 18.5], "..."]]},
              "properties": {"Name": "Plot A", "description": "Test plot"}}]}
```

## Architecture

```
config/                  Django project (settings, root urls)
files/
  models.py              GeoFile (upload + status) and GeoFeature (feature + stored measurement)
  serializers.py         Upload validation, response shapes
  views.py               GeoFileViewSet: thin HTTP layer
  services/
    readers.py           Zip/KML -> list[RawFeature]  (safe extraction, CRS resolution)
    crs.py               CRS labels, UTM / LAEA selection, cached transformers
    measurements.py      Pure function: (geometry, crs) -> Measurement
    processing.py        Orchestrates read -> measure -> persist, manages status
  tests/                 Unit tests (measurement accuracy) + API tests
```

**File-processing flow**
1. `POST /api/files/` validates extension and size, saves the file, creates a `GeoFile` (`PENDING`).
2. `process_geofile` sets `PROCESSING` and reads the file. Zips are extracted to a temp dir with zip-slip and
   zip-bomb checks, and required companions (`.shx`, `.dbf`) are verified. Each layer is read with `pyogrio`
   (KML folders become layers; Z values are dropped).
3. Every feature becomes a `GeoFeature` row (index, layer, geometry type, GeoJSON geometry, CRS, properties),
   bulk-inserted in one transaction.
4. Status becomes `COMPLETED`, or `FAILED` with an `error_message`.

**Measurement flow** (`measurements.py`)
1. Null/empty -> `SKIPPED`; Point/MultiPoint -> `NOT_REQUIRED`; other types -> `UNSUPPORTED`.
2. Reproject the geometry to WGS84 and take its centroid (lon, lat).
3. Pick a local projected CRS (below), reproject, then use shapely `.area` / `.length`.
4. Results are stored on the feature at upload time, so the measurements endpoint is a plain read.

**CRS handling**
- KML is always EPSG:4326. Shapefiles use the CRS in their `.prj`. If absent, the upload fails with a clear message
  unless the caller supplies `crs`. The system never silently assumes a CRS.
- Source CRS can be geographic or projected (even in feet); it is normalised to WGS84 first, then measured in a
  local metric CRS. The original geometry and CRS are stored unchanged.
- **Area:** Lambert Azimuthal Equal Area centred on the feature's centroid. Equal-area preserves area by definition.
- **Length:** UTM zone of the feature's centroid (EPSG:326xx north / 327xx south), with UPS polar CRSs beyond
  84°N/80°S. UTM is conformal with under ~0.04% scale error inside its zone.
- Tests check results against pyproj's geodesic calculations on the WGS84 ellipsoid (within 0.1%).

## Design Decisions

| Decision | Why | Alternatives considered |
|---|---|---|
| Plain DRF + `pyogrio`/`shapely`/`pyproj`, no GeoDjango | Zero system dependencies (no GDAL/PostGIS install); easy to run anywhere | GeoDjango + PostGIS: better for spatial queries, heavy setup for this scope |
| Per-feature local projection | Accurate for datasets anywhere on Earth; a single fixed CRS (e.g. EPSG:3857) distorts area badly away from the equator | One UTM zone per file (breaks for large/multi-zone files); geodesic only (accurate, but the brief asks for projected CRS) |
| Different projection for area vs length | Each property is preserved by a different projection class | One UTM for both: simpler, slightly less exact for area |
| Measurements computed and stored at upload | Reads are cheap; results are reproducible | Compute on request: no storage, repeated work |
| Synchronous processing | Simple, deterministic, sufficient for files up to the 25 MB limit | Celery/RQ background jobs (see future scope) |
| Geometry stored as GeoJSON in `JSONField` | Portable, works on SQLite | WKT/WKB text, PostGIS geometry |
| `422` + persisted `FAILED` record for unprocessable files | Client can still query why it failed | Return `400` and discard |
| MultiPolygon/MultiLineString measured as sums | Shapefile polygons are routinely multi-part | Report only single-part types |

## Learnings

- Degrees are not metres: a 0.01° × 0.01° box near Pune is ~1.17 km², while the same numbers in a naive calculation give 0.0001.
- Shapefiles are a bundle of files, and a missing `.prj` is the most common real-world failure, so it needs an explicit, helpful error path.
- Equal-area and conformal projections solve different problems; choosing per measurement type matters.
- Handling untrusted zips (zip-slip, zip-bombs) is part of "file upload", not an afterthought.

## Future Scope

- Async processing (Celery + Redis) with status polling and webhooks for large files; streaming reads for very large datasets.
- PostgreSQL/PostGIS for spatial queries (bbox filters, intersections) and spatial indexes.
- Handle antimeridian-crossing features (centroid currently assumes no wrap) and `GeometryCollection` measurement.
- More formats (GeoJSON, GeoPackage, KMZ); geodesic cross-check option; perimeter and centroid outputs.
- OpenAPI docs (drf-spectacular), authentication, rate limiting, Dockerfile + CI, file retention/cleanup policy.

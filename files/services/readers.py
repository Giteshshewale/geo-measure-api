"""Read Shapefile (zipped) and KML files into a uniform list of RawFeature."""
import datetime as dt
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from django.conf import settings
from pyogrio import list_layers, raw
from pyproj import CRS
from pyproj.exceptions import CRSError
from shapely.geometry.base import BaseGeometry


class GeoFileError(Exception):
    """The uploaded file is unreadable / invalid. Message is safe to show to the client."""


@dataclass
class RawFeature:
    index: int
    layer: str
    geometry: BaseGeometry | None
    crs: CRS
    properties: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
def read_features(path: Path, file_type: str, fallback_crs: str | None = None) -> list[RawFeature]:
    if file_type == 'KML':
        return _read_dataset(path, fallback_crs)
    if file_type == 'SHAPEFILE':
        with tempfile.TemporaryDirectory() as tmp:
            shp_files = _safe_extract_zip(path, Path(tmp))
            features: list[RawFeature] = []
            for shp in shp_files:
                features.extend(_read_dataset(shp, fallback_crs, start_index=len(features)))
            return features
    raise GeoFileError(f'Unsupported file type: {file_type}')


# ---------------------------------------------------------------------------
def _safe_extract_zip(zip_path: Path, dest: Path) -> list[Path]:
    """Extract with zip-slip and zip-bomb protection; return the .shp files found."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise GeoFileError('File is not a valid zip archive.')
    with zf:
        total = sum(i.file_size for i in zf.infolist())
        if total > settings.MAX_UNCOMPRESSED_BYTES:
            raise GeoFileError('Zip archive is too large when uncompressed.')
        dest_resolved = dest.resolve()
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if dest_resolved != target and dest_resolved not in target.parents:
                raise GeoFileError('Zip archive contains unsafe paths.')
        zf.extractall(dest)

    shp_files = sorted(p for p in dest.rglob('*') if p.suffix.lower() == '.shp' and '__MACOSX' not in p.parts)
    if not shp_files:
        raise GeoFileError('No .shp file found inside the zip archive.')
    for shp in shp_files:
        siblings = {p.suffix.lower() for p in shp.parent.glob(f'{shp.stem}.*')}
        missing = {'.shx', '.dbf'} - siblings
        if missing:
            raise GeoFileError(f"Shapefile '{shp.name}' is missing required companion file(s): {', '.join(sorted(missing))}.")
    return shp_files


def _read_dataset(path: Path, fallback_crs: str | None, start_index: int = 0) -> list[RawFeature]:
    try:
        layers = [name for name, _ in list_layers(path)]
    except Exception as exc:
        raise GeoFileError(f'Could not open geospatial file: {exc}')
    if not layers:
        raise GeoFileError('No layers found in file.')

    features: list[RawFeature] = []
    for layer in layers:
        try:
            meta, _fids, geoms, field_data = raw.read(path, layer=layer, force_2d=True)
        except Exception as exc:
            raise GeoFileError(f"Could not read layer '{layer}': {exc}")
        crs = _resolve_crs(meta.get('crs'), fallback_crs, layer)
        fields = list(meta['fields'])
        for i, wkb in enumerate(geoms):
            geom = shapely.from_wkb(wkb) if wkb is not None else None
            props = {name: _jsonable(col[i]) for name, col in zip(fields, field_data)}
            features.append(RawFeature(start_index + len(features), str(layer), geom, crs, props))
    return features


def _resolve_crs(file_crs, fallback_crs, layer) -> CRS:
    try:
        if file_crs:
            return CRS.from_user_input(file_crs)
        if fallback_crs:
            return CRS.from_user_input(fallback_crs)
    except CRSError as exc:
        raise GeoFileError(f'Invalid CRS: {exc}')
    raise GeoFileError(
        f"Layer '{layer}' has no CRS (missing .prj?). Re-upload with a .prj file, "
        "or pass the 'crs' form field (e.g. EPSG:4326) to declare it."
    )


def _jsonable(value):
    """Convert numpy / datetime scalars returned by GDAL into JSON-safe Python values."""
    if value is None:
        return None
    if isinstance(value, np.generic):
        if isinstance(value, np.datetime64):
            return None if np.isnat(value) else str(value)
        value = value.item()
    if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))):
        return None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return value

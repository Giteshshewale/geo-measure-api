"""CRS helpers: labelling and choosing a local projected CRS for measurements."""
from functools import lru_cache

from pyproj import CRS, Transformer

WGS84 = CRS.from_epsg(4326)


def crs_label(crs: CRS) -> str:
    """Return 'EPSG:xxxx' when the CRS can be identified, else its name."""
    auth = crs.to_authority(min_confidence=70)
    if auth:
        return f'{auth[0]}:{auth[1]}'
    return crs.name


@lru_cache(maxsize=256)
def get_transformer(src_wkt: str, dst_wkt: str) -> Transformer:
    # always_xy -> (lon, lat) / (easting, northing) order regardless of the CRS axis definition
    return Transformer.from_crs(CRS.from_wkt(src_wkt), CRS.from_wkt(dst_wkt), always_xy=True)


def utm_crs_for(lon: float, lat: float) -> CRS:
    """UTM zone containing (lon, lat); UPS polar stereographic beyond UTM's 84N/80S limits."""
    if lat > 84:
        return CRS.from_epsg(32661)  # WGS 84 / UPS North
    if lat < -80:
        return CRS.from_epsg(32761)  # WGS 84 / UPS South
    zone = min(max(int((lon + 180) // 6) + 1, 1), 60)
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def laea_crs_for(lon: float, lat: float) -> CRS:
    """Lambert Azimuthal Equal Area centred on (lon, lat): preserves area exactly."""
    return CRS.from_proj4(
        f'+proj=laea +lat_0={lat:.6f} +lon_0={lon:.6f} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs'
    )

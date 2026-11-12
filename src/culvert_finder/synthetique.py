"""Scène synthétique : vallée, route en remblai sans buse, route avec pont.

Sert aux tests et à la démonstration hors ligne (`culvert-finder demo`).
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import LineString

from culvert_finder.data import CRS_L93


def scene(taille: int = 200, res: float = 1.0, decalage_trace: float = 0.0):
    """Renvoie (mnt, transform, cours_eau, infrastructures, ouvrages_osm).

    `decalage_trace` décale le tracé vectoriel du cours d'eau par rapport au thalweg du
    MNT, comme c'est souvent le cas entre la BD TOPO et le LiDAR.

    - vallée en V orientée ouest → est, pente 1 % ;
    - route n°1 (x = 100) : remblai de 12 m d'altitude **sans ouverture** → faux barrage ;
    - route n°2 (x = 150) : remblai avec un pont de 12 m d'ouverture → écoulement libre ;
    - OpenStreetMap connaît une buse sous la route n°1.
    """
    transform = from_origin(0, taille * res, res, res)
    xc = (np.arange(taille) + 0.5) * res
    yc = taille * res - (np.arange(taille) + 0.5) * res
    x, y = np.meshgrid(xc, yc)
    axe_y = taille * res / 2 + 0.5
    mnt = 10 - 0.01 * x + 0.05 * np.abs(y - axe_y)

    remblai1 = np.abs(x - 100) <= 5
    mnt[remblai1] = np.maximum(mnt[remblai1], 12.0)
    remblai2 = (np.abs(x - 150) <= 5) & (np.abs(y - axe_y) > 6)
    mnt[remblai2] = np.maximum(mnt[remblai2], 12.0)

    cours_eau = gpd.GeoDataFrame(
        {"nature": ["Cours d'eau"]},
        geometry=[LineString([(0, axe_y + decalage_trace), (taille * res, axe_y + decalage_trace)])],
        crs=CRS_L93,
    )
    infras = gpd.GeoDataFrame(
        {"type_infra": ["route", "route"], "position_par_rapport_au_sol": ["0", "0"]},
        geometry=[LineString([(100, 0), (100, taille * res)]), LineString([(150, 0), (150, taille * res)])],
        crs=CRS_L93,
    )
    osm = gpd.GeoDataFrame(
        {"type_ouvrage": ["buse"], "osm_id": [1]},
        geometry=[LineString([(94, axe_y + 1), (106, axe_y + 1)])],
        crs=CRS_L93,
    )
    return mnt, transform, cours_eau, infras, osm

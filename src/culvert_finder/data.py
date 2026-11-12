"""Téléchargement et lecture des données : IGN Géoplateforme, OpenStreetMap, fichiers locaux."""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
import shapely
from pyproj import Transformer
from rasterio.transform import from_bounds
from shapely.geometry import LineString

log = logging.getLogger(__name__)

CRS_L93 = "EPSG:2154"
WFS_URL = "https://data.geopf.fr/wfs/ows"
WMS_URL = "https://data.geopf.fr/wms-r/wms"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
COUCHE_MNT = "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES"  # RGE ALTI 1 m
USER_AGENT = "culvert-finder/0.1 (https://github.com/myriam-idam/culvert-finder)"

COUCHES_BDTOPO = {
    "cours_eau": "BDTOPO_V3:troncon_hydrographique",
    "routes": "BDTOPO_V3:troncon_de_route",
    "voies_ferrees": "BDTOPO_V3:troncon_de_voie_ferree",
}
# Attributs BD TOPO conservés (les autres sont ignorés)
_COLONNES = ("nature", "importance", "position_par_rapport_au_sol")

Emprise = tuple[float, float, float, float]  # xmin, ymin, xmax, ymax en Lambert 93


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def gdf_vide(colonnes: tuple[str, ...] = ()) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame({c: [] for c in colonnes}, geometry=[], crs=CRS_L93)


def telecharger_bdtopo(couche: str, emprise: Emprise, taille_page: int = 5000) -> gpd.GeoDataFrame:
    """Télécharge une couche BD TOPO (WFS Géoplateforme) sur l'emprise, en Lambert 93."""
    xmin, ymin, xmax, ymax = emprise
    objets: list[dict] = []
    debut = 0
    with _session() as s:
        while True:
            params = {
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": couche,
                "SRSNAME": CRS_L93,
                "BBOX": f"{xmin},{ymin},{xmax},{ymax},urn:ogc:def:crs:EPSG::2154",
                "OUTPUTFORMAT": "application/json",
                "COUNT": taille_page,
                "STARTINDEX": debut,
            }
            r = s.get(WFS_URL, params=params, timeout=180)
            r.raise_for_status()
            lot = r.json().get("features", [])
            objets.extend(lot)
            if len(lot) < taille_page:
                break
            debut += taille_page
    log.info("%s : %d objets", couche, len(objets))
    if not objets:
        return gdf_vide()
    gdf = gpd.GeoDataFrame.from_features(objets, crs=CRS_L93)
    gdf = gdf[[c for c in _COLONNES if c in gdf.columns] + ["geometry"]]
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf["geometry"] = shapely.force_2d(gdf.geometry.values)  # retire le Z (-1000 = inconnu)
    return gdf.reset_index(drop=True)


def telecharger_mnt(emprise: Emprise, resolution: float = 1.0, tuile_px: int = 2000):
    """Télécharge le MNT RGE ALTI (WMS-R Géoplateforme) par tuiles.

    Renvoie (mnt, transform) : tableau float64 (NaN = sans donnée) et géoréférencement.
    """
    xmin, ymin, xmax, ymax = emprise
    largeur = int(round((xmax - xmin) / resolution))
    hauteur = int(round((ymax - ymin) / resolution))
    xmax, ymin = xmin + largeur * resolution, ymax - hauteur * resolution
    mnt = np.full((hauteur, largeur), np.nan)
    with _session() as s:
        for r0 in range(0, hauteur, tuile_px):
            for c0 in range(0, largeur, tuile_px):
                h, w = min(tuile_px, hauteur - r0), min(tuile_px, largeur - c0)
                txmin = xmin + c0 * resolution
                tymax = ymax - r0 * resolution
                params = {
                    "SERVICE": "WMS",
                    "VERSION": "1.3.0",
                    "REQUEST": "GetMap",
                    "LAYERS": COUCHE_MNT,
                    "STYLES": "",
                    "CRS": CRS_L93,
                    "BBOX": f"{txmin},{tymax - h * resolution},{txmin + w * resolution},{tymax}",
                    "WIDTH": w,
                    "HEIGHT": h,
                    "FORMAT": "image/geotiff",
                }
                r = s.get(WMS_URL, params=params, timeout=300)
                r.raise_for_status()
                if "tiff" not in r.headers.get("content-type", ""):
                    raise RuntimeError(f"Réponse inattendue du service MNT : {r.text[:300]}")
                with rasterio.MemoryFile(r.content) as mf, mf.open() as src:
                    mnt[r0 : r0 + h, c0 : c0 + w] = src.read(1)
    mnt[mnt < -1000] = np.nan  # valeur « sans donnée » de l'IGN (-99999)
    return mnt, from_bounds(xmin, ymin, xmax, ymax, largeur, hauteur)


def telecharger_ouvrages_osm(emprise: Emprise) -> gpd.GeoDataFrame:
    """Buses (tunnel=culvert) et ponts (bridge=*) cartographiés dans OpenStreetMap."""
    xmin, ymin, xmax, ymax = emprise
    t = Transformer.from_crs(CRS_L93, "EPSG:4326", always_xy=True)
    lons, lats = t.transform([xmin, xmax, xmin, xmax], [ymin, ymin, ymax, ymax])
    bb = f"{min(lats)},{min(lons)},{max(lats)},{max(lons)}"
    requete = (
        f'[out:json][timeout:90];(way["tunnel"="culvert"]({bb});'
        f'way["bridge"]["bridge"!="no"]({bb}););out geom;'
    )
    colonnes = ("type_ouvrage", "osm_id")
    elements = None
    with _session() as s:
        for url in OVERPASS_URLS:  # serveurs publics parfois saturés : on essaie les miroirs
            try:
                r = s.post(url, data={"data": requete}, timeout=120)
                r.raise_for_status()
                elements = r.json().get("elements", [])
                break
            except (requests.RequestException, ValueError) as exc:
                log.warning("Overpass %s indisponible (%s)", url, exc)
    if elements is None:
        log.warning("OpenStreetMap indisponible, analyse sans ouvrages OSM")
        return gdf_vide(colonnes)
    lignes = []
    for el in elements:
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        tags = el.get("tags", {})
        lignes.append(
            {
                "type_ouvrage": "buse" if tags.get("tunnel") == "culvert" else "pont",
                "osm_id": el["id"],
                "geometry": LineString([(p["lon"], p["lat"]) for p in geom]),
            }
        )
    log.info("OpenStreetMap : %d ouvrages", len(lignes))
    if not lignes:
        return gdf_vide(colonnes)
    return gpd.GeoDataFrame(lignes, geometry="geometry", crs="EPSG:4326").to_crs(CRS_L93)


def lire_mnt(chemin: str):
    """Lit un MNT local (GeoTIFF, ASC…). Renvoie (mnt, transform, crs)."""
    with rasterio.open(chemin) as src:
        mnt = src.read(1, masked=True).astype("float64").filled(np.nan)
        return mnt, src.transform, src.crs


def ecrire_raster(chemin, tableau: np.ndarray, transform, crs=CRS_L93) -> None:
    with rasterio.open(
        chemin,
        "w",
        driver="GTiff",
        height=tableau.shape[0],
        width=tableau.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=-99999.0,
        compress="deflate",
    ) as dst:
        dst.write(np.where(np.isnan(tableau), -99999.0, tableau).astype("float32"), 1)


def infrastructures(routes: gpd.GeoDataFrame, voies_ferrees: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Fusionne routes et voies ferrées en une couche « infrastructures » (colonne type_infra)."""
    parts = []
    for gdf, nom in ((routes, "route"), (voies_ferrees, "voie ferrée")):
        if len(gdf):
            g = gdf.copy()
            g["type_infra"] = nom
            parts.append(g)
    if not parts:
        return gdf_vide(("type_infra",))
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=CRS_L93)

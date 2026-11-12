"""Détection des franchissements cours d'eau × infrastructures et calcul de leurs indicateurs."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point

from culvert_finder.config import Parametres
from culvert_finder.mnt import lignes_colonnes, nanmax, nanmin, profil_en_long


def fusionner_cours_eau(cours_eau: gpd.GeoDataFrame) -> list[LineString]:
    """Assemble les tronçons BD TOPO en lignes continues (pour des profils non tronqués)."""
    if len(cours_eau) == 0:
        return []
    fusion = shapely.line_merge(shapely.union_all(cours_eau.geometry.values))
    geoms = getattr(fusion, "geoms", [fusion])
    return [g for g in geoms if isinstance(g, LineString) and not g.is_empty and g.length > 0]


def _points(geom) -> list[Point]:
    if geom.is_empty:
        return []
    if isinstance(geom, Point):
        return [geom]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _points(g)]
    # Superposition linéaire (cours d'eau longeant la route) : on garde le milieu
    return [geom.interpolate(0.5, normalized=True)]


def trouver_franchissements(
    lignes: list[LineString], infras: gpd.GeoDataFrame, espacement_min: float
) -> gpd.GeoDataFrame:
    """Points d'intersection entre cours d'eau et routes / voies ferrées."""
    colonnes = ["type_infra", "pont_bdtopo", "indice_cours_eau"]
    if not lignes or len(infras) == 0:
        return gpd.GeoDataFrame({c: [] for c in colonnes}, geometry=[], crs=infras.crs)
    arbre = shapely.STRtree(lignes)
    # BD TOPO : position_par_rapport_au_sol > 0 = tronçon sur un pont / viaduc
    if "position_par_rapport_au_sol" in infras:
        ponts = pd.to_numeric(infras["position_par_rapport_au_sol"], errors="coerce").fillna(0) > 0
    else:
        ponts = pd.Series(False, index=infras.index)
    candidats = []
    for type_infra, pont, geom in zip(infras["type_infra"], ponts, infras.geometry):
        for j in arbre.query(geom, predicate="intersects"):
            for p in _points(geom.intersection(lignes[j])):
                candidats.append((p, type_infra, bool(pont), int(j)))

    gardes, xy = [], np.empty((0, 2))
    for p, type_infra, pont, j in candidats:
        if len(xy) and np.hypot(xy[:, 0] - p.x, xy[:, 1] - p.y).min() < espacement_min:
            continue
        gardes.append({"type_infra": type_infra, "pont_bdtopo": pont, "indice_cours_eau": j, "geometry": p})
        xy = np.vstack([xy, [p.x, p.y]])
    if not gardes:
        return gpd.GeoDataFrame({c: [] for c in colonnes}, geometry=[], crs=infras.crs)
    return gpd.GeoDataFrame(gardes, geometry="geometry", crs=infras.crs)


def calculer_indicateurs(
    franch: gpd.GeoDataFrame,
    lignes: list[LineString],
    mnt_thalweg: np.ndarray,
    profondeur: np.ndarray,
    transform,
    params: Parametres,
    ouvrages_osm: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Ajoute à chaque franchissement :

    - hauteur_remblai_m : hauteur dont l'eau doit monter pour franchir l'infrastructure
      dans le MNT (point haut au droit du remblai - plus haut des deux points bas amont/aval) ;
    - profondeur_cuvette_m : profondeur maximale de la cuvette artificielle à proximité ;
    - ouvrage_osm / type_ouvrage_osm / distance_osm_m : ouvrage connu dans OpenStreetMap.
    """
    franch = franch.copy()
    res = abs(transform.a)
    k = max(1, int(round(params.rayon_cuvette / res)))
    hauteurs, profondeurs = [], []
    for p, j in zip(franch.geometry, franch["indice_cours_eau"]):
        off, _, _, z = profil_en_long(lignes[int(j)], p, mnt_thalweg, transform, params.demi_longueur_profil)
        c = params.demi_largeur_remblai
        z_centre = nanmax(z[np.abs(off) <= c])
        z_bas = max(nanmin(z[off < -c]), nanmin(z[off > c]))
        hauteurs.append(z_centre - z_bas)

        (r,), (col,) = lignes_colonnes(transform, [p.x], [p.y])
        fenetre = profondeur[max(r - k, 0) : r + k + 1, max(col - k, 0) : col + k + 1]
        profondeurs.append(nanmax(fenetre) if fenetre.size else np.nan)

    franch["hauteur_remblai_m"] = np.round(np.clip(hauteurs, 0, None), 2)
    franch["profondeur_cuvette_m"] = np.round(np.clip(profondeurs, 0, None), 2)

    franch["ouvrage_osm"] = False
    franch["type_ouvrage_osm"] = ""
    franch["distance_osm_m"] = np.nan
    if ouvrages_osm is not None and len(ouvrages_osm) and len(franch):
        arbre = shapely.STRtree(ouvrages_osm.geometry.values)
        idx, dist = arbre.query_nearest(franch.geometry.values, return_distance=True, all_matches=False)
        franch.loc[franch.index[idx[0]], "distance_osm_m"] = np.round(dist, 1)
        franch.loc[franch.index[idx[0]], "type_ouvrage_osm"] = ouvrages_osm["type_ouvrage"].values[idx[1]]
        proche = franch["distance_osm_m"] <= params.distance_osm
        franch["ouvrage_osm"] = proche.fillna(False)
        franch.loc[~franch["ouvrage_osm"], "type_ouvrage_osm"] = ""
    return franch

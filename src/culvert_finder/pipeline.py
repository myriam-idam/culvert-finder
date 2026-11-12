"""Chaîne de traitement complète."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from culvert_finder import data
from culvert_finder.config import Parametres
from culvert_finder.correction import creuser
from culvert_finder.detection import calculer_indicateurs, fusionner_cours_eau, trouver_franchissements
from culvert_finder.mnt import mnt_thalweg, profondeur_cuvettes
from culvert_finder.score import scorer

log = logging.getLogger(__name__)


@dataclass
class Resultat:
    mnt: np.ndarray
    mnt_corrige: np.ndarray
    transform: object
    franchissements: gpd.GeoDataFrame
    lignes_cours_eau: list[LineString]
    infrastructures: gpd.GeoDataFrame
    profondeur_avant: np.ndarray
    profondeur_apres: np.ndarray
    params: Parametres = field(default_factory=Parametres)

    @property
    def surface_cellule(self) -> float:
        return abs(self.transform.a * self.transform.e)

    @property
    def volume_avant_m3(self) -> float:
        return float(np.nansum(self.profondeur_avant) * self.surface_cellule)

    @property
    def volume_apres_m3(self) -> float:
        return float(np.nansum(self.profondeur_apres) * self.surface_cellule)

    def resume(self) -> dict:
        f = self.franchissements
        reduction = 100 * (1 - self.volume_apres_m3 / self.volume_avant_m3) if self.volume_avant_m3 else 0.0
        return {
            "franchissements": int(len(f)),
            "par_classe": {k: int(v) for k, v in f["classe"].value_counts().items()} if len(f) else {},
            "corriges_dans_mnt": int(f["corrige"].sum()) if len(f) else 0,
            "confirmes_par_osm": int((f["corrige"] & f["ouvrage_osm"]).sum()) if len(f) else 0,
            "volume_cuvettes_avant_m3": round(self.volume_avant_m3, 1),
            "volume_cuvettes_apres_m3": round(self.volume_apres_m3, 1),
            "reduction_volume_cuvettes_pct": round(reduction, 1),
        }


def analyser(
    mnt: np.ndarray,
    transform,
    cours_eau: gpd.GeoDataFrame,
    infras: gpd.GeoDataFrame,
    ouvrages_osm: gpd.GeoDataFrame | None = None,
    params: Parametres | None = None,
) -> Resultat:
    """Analyse complète à partir de données déjà chargées (sans accès réseau)."""
    params = params or Parametres()
    res = abs(transform.a)
    mnt = mnt.astype("float64")

    log.info("Comblement des cuvettes du MNT brut…")
    prof_avant = profondeur_cuvettes(mnt)
    thalweg = mnt_thalweg(mnt, int(round(params.rayon_thalweg / res)))

    log.info("Recherche des franchissements…")
    lignes = fusionner_cours_eau(cours_eau)
    franch = trouver_franchissements(lignes, infras, params.espacement_min)
    log.info("%d franchissements trouvés", len(franch))

    franch = calculer_indicateurs(franch, lignes, thalweg, prof_avant, transform, params, ouvrages_osm)
    franch = scorer(franch, params)

    log.info("Correction du MNT…")
    mnt_corr, corriges = creuser(mnt, thalweg, franch, lignes, transform, params)
    franch["corrige"] = corriges
    prof_apres = profondeur_cuvettes(mnt_corr)

    return Resultat(mnt, mnt_corr, transform, franch, lignes, infras, prof_avant, prof_apres, params)


def executer(
    sortie: str | Path,
    emprise: data.Emprise | None = None,
    chemin_mnt: str | None = None,
    resolution: float = 1.0,
    avec_osm: bool = True,
    params: Parametres | None = None,
) -> Resultat:
    """Télécharge les données, lance l'analyse et écrit les résultats dans `sortie`."""
    from culvert_finder.rapport import ecrire_rapport

    sortie = Path(sortie)
    sortie.mkdir(parents=True, exist_ok=True)

    if chemin_mnt:
        log.info("Lecture du MNT %s", chemin_mnt)
        mnt, transform, crs = data.lire_mnt(chemin_mnt)
        if crs and crs.to_epsg() != 2154:
            raise ValueError("Le MNT doit être en Lambert 93 (EPSG:2154).")
        if emprise is None:
            h, w = mnt.shape
            emprise = (transform.c, transform.f + h * transform.e, transform.c + w * transform.a, transform.f)
    else:
        if emprise is None:
            raise ValueError("Indiquez une emprise ou un fichier MNT.")
        log.info("Téléchargement du MNT RGE ALTI (%s m)…", resolution)
        mnt, transform = data.telecharger_mnt(emprise, resolution)

    log.info("Téléchargement BD TOPO…")
    cours_eau = data.telecharger_bdtopo(data.COUCHES_BDTOPO["cours_eau"], emprise)
    infras = data.infrastructures(
        data.telecharger_bdtopo(data.COUCHES_BDTOPO["routes"], emprise),
        data.telecharger_bdtopo(data.COUCHES_BDTOPO["voies_ferrees"], emprise),
    )
    osm = data.telecharger_ouvrages_osm(emprise) if avec_osm else None

    res = analyser(mnt, transform, cours_eau, infras, osm, params)
    sauvegarder(res, sortie, cours_eau=cours_eau, ouvrages_osm=osm)
    ecrire_rapport(res, sortie)
    return res


def sauvegarder(res: Resultat, sortie: Path, cours_eau=None, ouvrages_osm=None) -> None:
    gpkg = sortie / "culvert_finder.gpkg"
    if len(res.franchissements):
        res.franchissements.drop(columns=["indice_cours_eau"]).to_file(gpkg, layer="franchissements")
    if cours_eau is not None and len(cours_eau):
        cours_eau.to_file(gpkg, layer="cours_eau")
    if len(res.infrastructures):
        res.infrastructures.to_file(gpkg, layer="infrastructures")
    if ouvrages_osm is not None and len(ouvrages_osm):
        ouvrages_osm.to_file(gpkg, layer="ouvrages_osm")
    data.ecrire_raster(sortie / "mnt_brut.tif", res.mnt, res.transform)
    data.ecrire_raster(sortie / "mnt_corrige.tif", res.mnt_corrige, res.transform)
    data.ecrire_raster(sortie / "cuvettes_avant.tif", res.profondeur_avant, res.transform)
    data.ecrire_raster(sortie / "cuvettes_apres.tif", res.profondeur_apres, res.transform)
    (sortie / "resume.json").write_text(json.dumps(res.resume(), indent=2, ensure_ascii=False), encoding="utf-8")

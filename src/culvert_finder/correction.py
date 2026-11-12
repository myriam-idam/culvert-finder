"""Correction du MNT : creusement d'un chenal à travers les remblais détectés (« burning »)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from culvert_finder.config import Parametres
from culvert_finder.mnt import lignes_colonnes, profil_en_long


def creuser(
    mnt: np.ndarray,
    mnt_thalweg: np.ndarray,
    franch: gpd.GeoDataFrame,
    lignes: list[LineString],
    transform,
    params: Parametres,
) -> tuple[np.ndarray, np.ndarray]:
    """Creuse le MNT au droit des franchissements dont le score dépasse le seuil.

    Entre le point bas amont et le point bas aval, l'altitude le long du cours d'eau est
    abaissée sur une droite reliant ces deux points : l'eau franchit le remblai comme
    par une buse. Renvoie (MNT corrigé, masque booléen des franchissements corrigés).
    """
    corrige = mnt.copy()
    corriges = np.zeros(len(franch), dtype=bool)
    w = params.demi_largeur_chenal
    c = params.demi_largeur_remblai
    for n, (p, j, score) in enumerate(zip(franch.geometry, franch["indice_cours_eau"], franch["score"])):
        if score < params.seuil_correction:
            continue
        off, xs, ys, z = profil_en_long(lignes[int(j)], p, mnt_thalweg, transform, params.demi_longueur_profil)
        gauche = np.where((off < -c) & np.isfinite(z))[0]
        droite = np.where((off > c) & np.isfinite(z))[0]
        if not len(gauche) or not len(droite):
            continue
        ig = gauche[np.argmin(z[gauche])]
        id_ = droite[np.argmin(z[droite])]
        segment = slice(ig, id_ + 1)
        cible = np.interp(off[segment], [off[ig], off[id_]], [z[ig], z[id_]])
        rows, cols = lignes_colonnes(transform, xs[segment], ys[segment])
        for r, col, t in zip(rows, cols, cible):
            if not (0 <= r < corrige.shape[0] and 0 <= col < corrige.shape[1]):
                continue
            bloc = corrige[max(r - w, 0) : r + w + 1, max(col - w, 0) : col + w + 1]
            np.fmin(bloc, t, out=bloc, where=np.isfinite(bloc))
        corriges[n] = True
    return corrige, corriges

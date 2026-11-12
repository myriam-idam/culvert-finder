"""Score « ouvrage manquant dans le MNT » (version 1 : règles expertes)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np

from culvert_finder.config import Parametres

CLASSE_PROBABLE = "ouvrage manquant probable"
CLASSE_VERIFIER = "à vérifier"
CLASSE_LIBRE = "écoulement libre"


def scorer(franch: gpd.GeoDataFrame, params: Parametres) -> gpd.GeoDataFrame:
    """Score entre 0 et 1 combinant la hauteur du remblai (60 %) et la cuvette amont (40 %)."""
    franch = franch.copy()
    s_remblai = np.clip(franch["hauteur_remblai_m"].fillna(0) / params.hauteur_remblai_ref, 0, 1)
    s_cuvette = np.clip(franch["profondeur_cuvette_m"].fillna(0) / params.profondeur_cuvette_ref, 0, 1)
    franch["score"] = np.round(0.6 * s_remblai + 0.4 * s_cuvette, 2)
    franch["classe"] = np.select(
        [franch["score"] >= params.seuil_correction, franch["score"] >= params.seuil_verification],
        [CLASSE_PROBABLE, CLASSE_VERIFIER],
        default=CLASSE_LIBRE,
    )
    return franch.sort_values("score", ascending=False).reset_index(drop=True)

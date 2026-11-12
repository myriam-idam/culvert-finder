import numpy as np
import pytest

from culvert_finder import Parametres, analyser
from culvert_finder.detection import fusionner_cours_eau, trouver_franchissements
from culvert_finder.mnt import combler_cuvettes, profondeur_cuvettes
from culvert_finder.score import CLASSE_LIBRE, CLASSE_PROBABLE
from culvert_finder.synthetique import scene


@pytest.fixture(scope="module")
def resultat():
    mnt, transform, cours_eau, infras, osm = scene()
    return analyser(mnt, transform, cours_eau, infras, osm)


def test_comblement_cuvette_simple():
    mnt = np.full((5, 5), 10.0)
    mnt[2, 2] = 7.0
    comble = combler_cuvettes(mnt)
    assert comble[2, 2] == pytest.approx(10.0)
    assert profondeur_cuvettes(mnt).sum() == pytest.approx(3.0)


def test_comblement_respecte_les_nan():
    mnt = np.full((5, 5), 10.0)
    mnt[2, 2] = 7.0
    mnt[0, 0] = np.nan
    assert np.isnan(combler_cuvettes(mnt)[0, 0])


def test_deux_franchissements_detectes():
    _, _, cours_eau, infras, _ = scene()
    f = trouver_franchissements(fusionner_cours_eau(cours_eau), infras, espacement_min=10)
    assert sorted(round(p.x) for p in f.geometry) == [100, 150]


def test_remblai_sans_ouvrage_est_detecte(resultat):
    f = resultat.franchissements.set_index(resultat.franchissements.geometry.x.round())
    assert f.loc[100, "classe"] == CLASSE_PROBABLE
    assert f.loc[100, "hauteur_remblai_m"] > 2
    assert f.loc[100, "corrige"]


def test_pont_ouvert_n_est_pas_corrige(resultat):
    f = resultat.franchissements.set_index(resultat.franchissements.geometry.x.round())
    assert f.loc[150, "classe"] == CLASSE_LIBRE
    assert not f.loc[150, "corrige"]


def test_association_osm(resultat):
    f = resultat.franchissements.set_index(resultat.franchissements.geometry.x.round())
    assert f.loc[100, "ouvrage_osm"] and f.loc[100, "type_ouvrage_osm"] == "buse"
    assert not f.loc[150, "ouvrage_osm"]


def test_correction_supprime_la_cuvette(resultat):
    assert resultat.volume_avant_m3 > 100
    assert resultat.volume_apres_m3 < 0.05 * resultat.volume_avant_m3
    assert resultat.resume()["reduction_volume_cuvettes_pct"] > 95


def test_correction_ne_releve_jamais_le_mnt(resultat):
    assert np.all(resultat.mnt_corrige <= resultat.mnt + 1e-9)


def test_seuil_eleve_desactive_la_correction():
    mnt, transform, cours_eau, infras, osm = scene()
    res = analyser(mnt, transform, cours_eau, infras, osm, Parametres(seuil_correction=1.01))
    assert not res.franchissements["corrige"].any()
    np.testing.assert_array_equal(res.mnt_corrige, res.mnt)

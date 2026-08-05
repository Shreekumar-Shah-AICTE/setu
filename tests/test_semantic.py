"""Tests for Stage 2 semantic matching + centroids."""
from __future__ import annotations

import math

import numpy as np

from app.classification.semantic import compute_centroids, load_centroids, semantic_scores
from app.llm.factory import get_llm_client
from app.llm.mock import hashed_embedding


def test_mock_embedding_is_1024_dims_and_unit_norm():
    v = hashed_embedding("ગામમાં વીજ નથી")
    assert len(v) == 1024
    assert abs(np.linalg.norm(v) - 1.0) < 1e-6


def test_mock_embedding_is_deterministic():
    assert hashed_embedding("ટ્રાન્સફોર્મર બળી ગયું") == hashed_embedding("ટ્રાન્સફોર્મર બળી ગયું")


def test_centroids_exist_and_are_unit_norm(db):
    centroids = load_centroids(db)
    # Ten real departments have centroids; OTHER does not.
    assert "OTHER" not in centroids
    assert len(centroids) >= 10
    for code, vec in centroids.items():
        assert len(vec) == 1024
        assert abs(np.linalg.norm(vec) - 1.0) < 1e-6, code


def test_semantic_scores_form_distribution(db):
    centroids = load_centroids(db)
    all_codes = list(centroids.keys()) + ["OTHER"]
    q = hashed_embedding("ટ્રાન્સફોર્મર બળી ગયું અંધારપટ વીજળી")
    scores = semantic_scores(q, centroids, 0.07, all_codes)
    assert abs(sum(scores.values()) - 1.0) < 1e-6
    assert scores["OTHER"] == 0.0
    # Energy-flavoured text should score ENERGY highest among centroids.
    assert max(scores, key=scores.get) == "ENERGY"


def test_recompute_is_idempotent(db):
    import asyncio

    client = get_llm_client()
    before = load_centroids(db)["ENERGY"]
    asyncio.run(compute_centroids(db, client))
    after = load_centroids(db)["ENERGY"]
    assert max(abs(a - b) for a, b in zip(before, after)) < 1e-9

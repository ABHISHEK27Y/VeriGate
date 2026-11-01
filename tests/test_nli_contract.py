"""Transformation contract for the pinned NLI cross-encoder (audit F13).

The verifier assumes ``CrossEncoder.predict`` returns RAW logits for the 3-class
NLI model and applies its own softmax over them. If a sentence-transformers
upgrade began applying an activation (e.g. softmax) inside ``predict``, the
verifier would double-transform and silently change every accept/reject, with no
other test failing. These checks assert the contract directly rather than
inferring it from value ranges, and are opt-in because they load the real model.

Run with: VERIGATE_NLI_CONTRACT_TEST=1 pytest tests/test_nli_contract.py
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from app.config import settings

pytestmark = pytest.mark.skipif(
    os.environ.get("VERIGATE_NLI_CONTRACT_TEST") != "1",
    reason="opt-in: loads the pinned NLI model (VERIGATE_NLI_CONTRACT_TEST=1)",
)

MULTI_CLASS_MIN = 2


def _load():
    import torch  # noqa: PLC0415
    from sentence_transformers import CrossEncoder  # noqa: PLC0415

    model = CrossEncoder(settings.nli_model, revision=settings.nli_revision or None)
    return model, torch


def test_predict_activation_is_identity_for_multiclass_nli() -> None:
    """predict() must not apply an activation; the verifier owns the softmax."""
    model, torch = _load()
    num_labels = int(model.model.config.num_labels)
    assert num_labels >= MULTI_CLASS_MIN, "NLI head must be multi-class"
    activation = getattr(model, "activation_fn", None)
    assert isinstance(activation, torch.nn.Identity), (
        f"predict() activation is {type(activation).__name__}, expected Identity; "
        "a non-identity activation would double-transform the verifier's softmax"
    )


def test_predict_matches_direct_model_logits() -> None:
    """predict() output equals a direct model forward (confirms raw logits)."""
    model, torch = _load()
    pair = ("The answer to what is the capital of France is Paris.", "Paris is the capital.")
    predicted = np.asarray(model.predict([pair])).reshape(-1)
    features = model.tokenizer(
        [pair[0]], [pair[1]], padding=True, truncation=True, return_tensors="pt"
    )
    with torch.no_grad():
        logits = model.model(**features).logits.reshape(-1).cpu().numpy()
    assert predicted.shape == logits.shape
    assert np.allclose(predicted, logits, atol=1e-4)
    # A raw-logit vector is not already a probability distribution.
    assert not np.isclose(predicted.sum(), 1.0) or bool((predicted < 0).any())


def test_exactly_one_entailment_label() -> None:
    model, _torch = _load()
    labels = model.model.config.id2label
    entail = [index for index, label in labels.items() if "entail" in str(label).lower()]
    assert len(entail) == 1, f"expected one entailment label, found {entail} in {labels}"

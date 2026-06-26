"""``StubProvider`` — a deterministic, no-network :class:`ProviderClient` driven by canned output.

This is what keeps the **whole** engine runnable for free (CI, the API, the eval harness): script
the parsed schema instances the model "would" return and run the real ``load → route → ground →
assemble`` pipeline against them with zero API calls. It lives in the **installed package** (not
``tests/``) because Split 05 (eval) and Split 06 (api) import it across layer boundaries.

The two factories (:func:`stub_for_path_report`, :func:`stub_for_intake`) preload a stub with the
§5 worked-example / intake canned outputs — transcribed from the ``pathDefs()`` / ``intakeDefs()``
constants in the ``Component`` inside ``app/ChartExtract.dc.html`` — **converted to the schema's
typed/enum-valid values** (the JS ``value``s are display strings: ``"1.4 cm"`` → ``1.4`` float,
``"Female"`` → ``"female"`` enum member), so a canned instance validates exactly as a live
``messages.parse`` result would.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..cost import Usage
from ..schemas import Field, IntakeSchema, ListField, PathologySchema
from .base import ProviderClient

#: A canned token usage roughly representative of a one-document Opus extraction — non-zero so
#: priced ``cost_usd`` is realistic (> 0) in offline runs.
_DEFAULT_USAGE = Usage(input_tokens=1200, output_tokens=180)


class StubProvider:
    """Plays canned structured outputs and a canned classification; records every call.

    Parameters
    ----------
    extract_results:
        Parsed schema instances returned by :meth:`extract`. Dispatch is **schema-matched**: a call
        pops the first queued instance whose type matches the requested ``schema_model``, so a
        pathology call and an intake call in the same run don't collide.
    classify_result:
        The ``(key, confidence)`` returned by :meth:`classify_doc_type`. Defaults to
        ``("unknown", 0.0)`` — a stub with no canned classification never silently guesses a type.
    usage:
        The :class:`Usage` reported for both calls (so a run prices a real, non-zero cost).
    model:
        The model id reported (drives cost keying). Defaults to ``"claude-opus-4-8"`` so offline
        runs price exactly as the live demo does.
    """

    def __init__(
        self,
        *,
        extract_results: list[BaseModel] | None = None,
        classify_result: tuple[str, float] = ("unknown", 0.0),
        usage: Usage | None = None,
        model: str = "claude-opus-4-8",
        provider: str = "stub",
    ) -> None:
        self.provider = provider
        self.model = model
        self._extract_results = list(extract_results or [])
        self._classify_result = classify_result
        self._usage = usage or _DEFAULT_USAGE
        #: Append-only record of ``(method, *args)`` for assertions.
        self.calls: list[tuple[Any, ...]] = []

    def extract(
        self, system: str, document_text: str, schema_model: type[BaseModel]
    ) -> tuple[BaseModel, Usage]:
        self.calls.append(("extract", system, document_text, schema_model))
        for i, item in enumerate(self._extract_results):
            if isinstance(item, schema_model):
                return self._extract_results.pop(i), self._usage
        raise LookupError(
            f"StubProvider has no canned extract result for {schema_model.__name__} "
            f"(queued: {[type(r).__name__ for r in self._extract_results]})"
        )

    def classify_doc_type(self, text: str) -> tuple[str, float, Usage]:
        self.calls.append(("classify_doc_type", text))
        key, conf = self._classify_result
        return key, conf, self._usage


# Static check: the stub satisfies the Protocol (caught at import, not only at runtime use).
_PROTOCOL_CHECK: type[ProviderClient] = StubProvider


# ---------------------------------------------------------------------------
# Convenience factories — the §5 worked example and the intake form, one-liner.
# ---------------------------------------------------------------------------


def _path_report_instance(*, caught: bool = False) -> PathologySchema:
    """The pathology canned output (typed/enum-valid), from ``pathDefs()`` in the UI mockup.

    With ``caught=True`` the ``lymph_nodes_positive`` field carries the proposed ``2`` and a span
    **not** in the document, so grounding nulls it to ``not_grounded`` and retains
    ``model_value=2`` — the caught-hallucination demo, identical in stub and live mode.
    """
    lymph = (
        Field(value=2, source_span="2 of 3 axillary nodes positive", confidence=0.71)
        if caught
        else Field(value=None, source_span="", confidence=0.0)
    )
    return PathologySchema(
        specimen=Field(
            value="Left breast core biopsy", source_span="Left breast core biopsy", confidence=0.96
        ),
        diagnosis=Field(
            value="Invasive ductal carcinoma",
            source_span="Invasive ductal carcinoma, grade 2",
            confidence=0.93,
        ),
        grade=Field(value="2", source_span="grade 2", confidence=0.9),
        tumor_size_cm=Field(value=1.4, source_span="Tumor size 1.4 cm", confidence=0.95),
        er_status=Field(value="positive", source_span="ER positive (90%)", confidence=0.94),
        pr_status=Field(value="positive", source_span="PR positive (40%)", confidence=0.92),
        her2_status=Field(value="negative", source_span="HER2 negative", confidence=0.93),
        margin_status=Field(
            value=None, source_span="Margins not assessed on this specimen", confidence=0.0
        ),
        lymph_nodes_positive=lymph,
    )


def _intake_instance() -> IntakeSchema:
    """The intake canned output (typed/enum-valid), from ``intakeDefs()`` in the UI mockup."""
    return IntakeSchema(
        patient_name=Field(value="Jane Doe", source_span="PATIENT: Jane Doe", confidence=0.97),
        dob=Field(value="1971-03-14", source_span="DOB: 1971-03-14", confidence=0.96),
        sex=Field(value="female", source_span="Sex: Female", confidence=0.95),
        chief_complaint=Field(
            value="Persistent cough", source_span="Persistent cough, 3 weeks", confidence=0.55
        ),
        medications=ListField(
            items=[
                Field(
                    value="Lisinopril 10 mg daily",
                    source_span="Lisinopril 10 mg daily",
                    confidence=0.95,
                ),
                Field(
                    value="Metformin 500 mg twice daily",
                    source_span="Metformin 500 mg twice daily",
                    confidence=0.94,
                ),
                Field(
                    value="Atorvastatin 20 mg nightly",
                    source_span="Atorvastatin 20 mg nightly",
                    confidence=0.93,
                ),
            ]
        ),
        allergies=ListField(
            items=[Field(value="Penicillin", source_span="Penicillin (rash)", confidence=0.94)]
        ),
        pcp=Field(value=None, source_span="", confidence=0.0),
    )


def stub_for_path_report(*, caught: bool = False) -> StubProvider:
    """A stub preloaded with the §5 pathology worked example + a ``"pathology"`` classification."""
    return StubProvider(
        extract_results=[_path_report_instance(caught=caught)],
        classify_result=("pathology", 0.97),
    )


def stub_for_intake() -> StubProvider:
    """A stub preloaded with the intake form output and an ``"intake"`` classification."""
    return StubProvider(
        extract_results=[_intake_instance()],
        classify_result=("intake", 0.95),
    )

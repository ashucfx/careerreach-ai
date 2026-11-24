import pytest
from careerreach.job_intelligence import (
    CompanyEvidenceValidationError,
    JobEvidenceValidationError,
    JobIntelligenceService,
)
from careerreach.schemas import (
    CompanyEvidenceQuote,
    CompanyResearchAnalysis,
    CompanyResearchFinding,
    JobAnalysis,
    JobRequirement,
)


def test_job_requirements_require_exact_quotes_from_the_job_description() -> None:
    analysis = JobAnalysis(
        role_summary="Build backend systems.",
        summary_quotes=["5+ years of Python experience"],
        requirements=[
            JobRequirement(
                requirement="Python experience",
                category="skill",
                required=True,
                source_quote="5+ years of Python experience",
            )
        ],
    )
    JobIntelligenceService._validate_job_evidence(
        analysis, "We are looking for someone with 5+ years of Python experience."
    )

    analysis.requirements[0].source_quote = "10 years of Go experience"
    with pytest.raises(JobEvidenceValidationError, match="absent from the source"):
        JobIntelligenceService._validate_job_evidence(analysis, "5+ years of Python experience")


def test_company_findings_require_quotes_from_their_cited_search_results() -> None:
    analysis = CompanyResearchAnalysis(
        summary="The company builds cloud software.",
        summary_quotes=[
            CompanyEvidenceQuote(evidence_id="brave:source-1", quote="We provide cloud software")
        ],
        findings=[
            CompanyResearchFinding(
                category="product",
                claim="The company provides cloud software.",
                source_quotes=[
                    CompanyEvidenceQuote(
                        evidence_id="brave:source-1", quote="We provide cloud software"
                    )
                ],
            )
        ],
    )
    JobIntelligenceService._validate_company_evidence(
        analysis, {"brave:source-1": "About us\nWe provide cloud software to teams."}
    )

    with pytest.raises(CompanyEvidenceValidationError, match="absent from its cited"):
        JobIntelligenceService._validate_company_evidence(
            analysis, {"brave:source-1": "About us\nWe provide collaboration software."}
        )


def test_job_role_signals_must_be_present_in_the_source_description() -> None:
    analysis = JobAnalysis(
        role_summary="Build backend systems.",
        summary_quotes=["Build backend systems."],
        seniority="Senior",
        employment_type="Full-time",
    )
    with pytest.raises(JobEvidenceValidationError, match="role signal is absent"):
        JobIntelligenceService._validate_job_evidence(analysis, "Build backend systems.")


def test_job_summary_requires_a_verbatim_supporting_quote() -> None:
    analysis = JobAnalysis(
        role_summary="This role includes equity compensation.",
        summary_quotes=["equity compensation"],
    )
    with pytest.raises(JobEvidenceValidationError, match="summary quote is absent"):
        JobIntelligenceService._validate_job_evidence(
            analysis, "Compensation details are not listed."
        )


def test_company_findings_cannot_cite_a_source_the_search_did_not_return() -> None:
    analysis = CompanyResearchAnalysis(
        summary="A sourced summary.",
        summary_quotes=[CompanyEvidenceQuote(evidence_id="unknown", quote="Exact quote")],
        findings=[
            CompanyResearchFinding(
                category="overview",
                claim="Claim from an unknown source.",
                source_quotes=[CompanyEvidenceQuote(evidence_id="unknown", quote="Exact quote")],
            )
        ],
    )
    with pytest.raises(CompanyEvidenceValidationError, match="absent from its cited"):
        JobIntelligenceService._validate_company_evidence(analysis, {})

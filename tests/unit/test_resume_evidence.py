import pytest
from careerreach.resumes import (
    MAX_RESUME_EXTRACTION_CHARACTERS,
    ResumeEvidenceValidationError,
    ResumeService,
    ResumeTextTooLongForExtraction,
)
from careerreach.schemas import ResumeExtraction, ResumeFact, ResumeSkillFact


def test_resume_extraction_requires_quotes_and_values_grounded_in_source_text() -> None:
    extraction = ResumeExtraction(
        full_name=ResumeFact(value="Ashu Shukla", source_quote="Ashu Shukla"),
        headline=ResumeFact(value="Senior Python Engineer", source_quote="Senior Python Engineer"),
        skills=[
            ResumeSkillFact(name="Python", source_quote="Python, FastAPI"),
            ResumeSkillFact(name="FastAPI", source_quote="Python, FastAPI"),
        ],
    )

    ResumeService._validate_evidence(
        extraction, "Ashu Shukla\nSenior Python Engineer\nPython, FastAPI"
    )


def test_resume_extraction_rejects_missing_quotes_and_unsupported_values() -> None:
    missing_source = ResumeExtraction(
        full_name=ResumeFact(value="Ashu Shukla", source_quote="Ashu Shukla")
    )
    with pytest.raises(ResumeEvidenceValidationError):
        ResumeService._validate_evidence(missing_source, "Candidate name")

    unsupported_value = ResumeExtraction(
        full_name=ResumeFact(value="Invented Candidate", source_quote="Ashu Shukla")
    )
    with pytest.raises(ResumeEvidenceValidationError):
        ResumeService._validate_evidence(unsupported_value, "Ashu Shukla")


def test_resume_extraction_has_a_bounded_model_input_size() -> None:
    ResumeService._validate_extraction_length("x" * MAX_RESUME_EXTRACTION_CHARACTERS)

    with pytest.raises(ResumeTextTooLongForExtraction):
        ResumeService._validate_extraction_length("x" * (MAX_RESUME_EXTRACTION_CHARACTERS + 1))

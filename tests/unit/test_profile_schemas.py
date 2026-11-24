import pytest
from careerreach.schemas import CandidateProfileWrite
from pydantic import ValidationError


def test_candidate_profile_rejects_duplicate_skills_case_insensitively() -> None:
    with pytest.raises(ValidationError, match="unique by name"):
        CandidateProfileWrite(
            full_name="Candidate One",
            skills=[{"name": "Python"}, {"name": "python"}],
        )


def test_candidate_profile_rejects_inconsistent_experience_dates() -> None:
    with pytest.raises(ValidationError, match="end_date"):
        CandidateProfileWrite(
            full_name="Candidate One",
            experiences=[
                {
                    "employer": "Example Systems",
                    "title": "Backend Engineer",
                    "start_date": "2024-01-01T00:00:00Z",
                    "end_date": "2023-01-01T00:00:00Z",
                }
            ],
        )

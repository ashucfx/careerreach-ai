from __future__ import annotations

from uuid import UUID, uuid4

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import Settings
from .schemas import CandidateProfile, CandidateProfileHistory, CandidateProfileWrite


class ProfileVersionRequired(ValueError):
    pass


class ProfileVersionConflict(ValueError):
    pass


class CandidateProfileService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _database_url(self) -> str:
        if self._settings.database_url is None:
            raise RuntimeError("Set CAREERREACH_DATABASE_URL to use candidate profiles.")
        return self._settings.database_url

    async def get(self, user_id: UUID) -> CandidateProfile | None:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._set_tenant(connection, user_id)
            return await self._load(connection, user_id)

    async def save(self, user_id: UUID, request: CandidateProfileWrite) -> CandidateProfile:
        try:
            async with (
                await AsyncConnection.connect(self._database_url()) as connection,
                connection.transaction(),
            ):
                await self._set_tenant(connection, user_id)
                cursor = await connection.execute(
                    "SELECT id, version FROM candidate_profile WHERE user_id = %s",
                    (user_id,),
                )
                current = await cursor.fetchone()
                if current is None:
                    if request.expected_version is not None:
                        raise ProfileVersionConflict("The candidate profile does not exist.")
                    profile_id = uuid4()
                    await connection.execute(
                        "INSERT INTO candidate_profile "
                        "(id, user_id, version, full_name, headline, summary, target_titles, "
                        "target_locations) "
                        "VALUES (%s, %s, 1, %s, %s, %s, %s, %s)",
                        (
                            profile_id,
                            user_id,
                            request.full_name,
                            request.headline,
                            request.summary,
                            request.target_titles,
                            request.target_locations,
                        ),
                    )
                else:
                    if request.expected_version is None:
                        raise ProfileVersionRequired(
                            "expected_version is required when updating an existing profile."
                        )
                    if request.expected_version != current[1]:
                        raise ProfileVersionConflict("The candidate profile version is stale.")
                    profile_id = current[0]
                    previous = await self._load(connection, user_id)
                    if previous is None:
                        raise ProfileVersionConflict("The candidate profile no longer exists.")
                    await connection.execute(
                        "INSERT INTO candidate_profile_history "
                        "(id, profile_id, user_id, version, snapshot) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (
                            uuid4(),
                            profile_id,
                            user_id,
                            previous.version,
                            Jsonb(previous.model_dump(mode="json")),
                        ),
                    )
                    cursor = await connection.execute(
                        "UPDATE candidate_profile SET version = version + 1, full_name = %s, "
                        "headline = %s, summary = %s, target_titles = %s, "
                        "target_locations = %s, "
                        "updated_at = now() WHERE id = %s AND user_id = %s AND version = %s "
                        "RETURNING version",
                        (
                            request.full_name,
                            request.headline,
                            request.summary,
                            request.target_titles,
                            request.target_locations,
                            profile_id,
                            user_id,
                            request.expected_version,
                        ),
                    )
                    if await cursor.fetchone() is None:
                        raise ProfileVersionConflict("The candidate profile version is stale.")
                await self._replace_children(connection, user_id, profile_id, request)
                profile = await self._load(connection, user_id)
                if profile is None:
                    raise RuntimeError("Candidate profile write did not return a profile.")
                return profile
        except UniqueViolation as exc:
            raise ProfileVersionConflict(
                "The candidate profile was updated by another request."
            ) from exc

    async def delete(self, user_id: UUID) -> None:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._set_tenant(connection, user_id)
            await connection.execute("DELETE FROM candidate_profile WHERE user_id = %s", (user_id,))

    async def history(self, user_id: UUID) -> list[CandidateProfileHistory]:
        async with (
            await AsyncConnection.connect(self._database_url()) as connection,
            connection.transaction(),
        ):
            await self._set_tenant(connection, user_id)
            async with connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT version, snapshot, created_at FROM candidate_profile_history "
                    "WHERE user_id = %s ORDER BY version DESC",
                    (user_id,),
                )
                rows = await cursor.fetchall()
        return [CandidateProfileHistory.model_validate(row) for row in rows]

    async def _set_tenant(self, connection: AsyncConnection, user_id: UUID) -> None:
        await connection.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))

    async def _load(self, connection: AsyncConnection, user_id: UUID) -> CandidateProfile | None:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT id, user_id, version, full_name, headline, summary, target_titles, "
                "target_locations, created_at, updated_at "
                "FROM candidate_profile WHERE user_id = %s",
                (user_id,),
            )
            profile = await cursor.fetchone()
            if profile is None:
                return None
            await cursor.execute(
                "SELECT id, name, proficiency, years_experience FROM candidate_skill "
                "WHERE user_id = %s ORDER BY lower(name)",
                (user_id,),
            )
            skills = await cursor.fetchall()
            await cursor.execute(
                "SELECT id, employer, title, location, description, start_date, end_date, "
                "currently_employed FROM candidate_experience WHERE user_id = %s "
                "ORDER BY start_date DESC, id",
                (user_id,),
            )
            experiences = await cursor.fetchall()
            await cursor.execute(
                "SELECT id, institution, credential, field_of_study, start_year, end_year "
                "FROM candidate_education WHERE user_id = %s "
                "ORDER BY end_year DESC NULLS LAST, id",
                (user_id,),
            )
            education = await cursor.fetchall()
        return CandidateProfile.model_validate(
            {
                **profile,
                "skills": skills,
                "experiences": experiences,
                "education": education,
            }
        )

    async def _replace_children(
        self,
        connection: AsyncConnection,
        user_id: UUID,
        profile_id: UUID,
        request: CandidateProfileWrite,
    ) -> None:
        await connection.execute("DELETE FROM candidate_skill WHERE user_id = %s", (user_id,))
        await connection.execute("DELETE FROM candidate_experience WHERE user_id = %s", (user_id,))
        await connection.execute("DELETE FROM candidate_education WHERE user_id = %s", (user_id,))
        if request.skills:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO candidate_skill "
                    "(id, profile_id, user_id, name, proficiency, years_experience) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (
                            uuid4(),
                            profile_id,
                            user_id,
                            skill.name,
                            skill.proficiency,
                            skill.years_experience,
                        )
                        for skill in request.skills
                    ],
                )
        if request.experiences:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO candidate_experience "
                    "(id, profile_id, user_id, employer, title, location, description, start_date, "
                    "end_date, currently_employed) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            uuid4(),
                            profile_id,
                            user_id,
                            item.employer,
                            item.title,
                            item.location,
                            item.description,
                            item.start_date,
                            item.end_date,
                            item.currently_employed,
                        )
                        for item in request.experiences
                    ],
                )
        if request.education:
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO candidate_education "
                    "(id, profile_id, user_id, institution, credential, field_of_study, "
                    "start_year, end_year) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        (
                            uuid4(),
                            profile_id,
                            user_id,
                            item.institution,
                            item.credential,
                            item.field_of_study,
                            item.start_year,
                            item.end_year,
                        )
                        for item in request.education
                    ],
                )

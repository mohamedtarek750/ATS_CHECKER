"""Skill normalization: the difference between matching and string comparison.

A candidate who wrote "MS SQL Server" has SQL. One who wrote "PowerBI" has Power BI.
Without this table, matching silently fails people over spelling, and the ones it
fails are disproportionately those who did not copy a template's exact wording.

The aliases are one-directional: many spellings map to one canonical name.
"""

from __future__ import annotations

import re

# canonical -> the spellings that mean it
ALIASES: dict[str, tuple[str, ...]] = {
    "SQL": (
        "sql", "t-sql", "tsql", "ms sql", "ms sql server", "mssql", "sql server",
        "pl/sql", "plsql", "ansi sql", "structured query language",
    ),
    "Python": ("python", "python3", "py"),
    "Power BI": ("power bi", "powerbi", "power-bi", "pbi", "power bi desktop"),
    "Tableau": ("tableau", "tableau desktop"),
    "Excel": ("excel", "ms excel", "microsoft excel", "advanced excel"),
    "Power Query": ("power query", "powerquery", "m query"),
    "Apache Spark": ("spark", "apache spark", "pyspark", "spark sql"),
    "Databricks": ("databricks", "azure databricks"),
    "Airflow": ("airflow", "apache airflow", "mwaa"),
    "Azure Data Factory": ("azure data factory", "adf", "data factory"),
    "dbt": ("dbt", "data build tool"),
    "Kafka": ("kafka", "apache kafka", "event hubs", "azure event hubs"),
    "Docker": ("docker", "containers", "containerisation", "containerization"),
    "Kubernetes": ("kubernetes", "k8s", "eks", "aks", "gke"),
    "Git": ("git", "github", "gitlab", "bitbucket", "version control"),
    "CI/CD": ("ci/cd", "cicd", "ci cd", "github actions", "jenkins", "azure devops"),
    "Azure": ("azure", "microsoft azure", "synapse", "azure synapse", "adls"),
    "AWS": ("aws", "amazon web services", "s3", "redshift", "glue"),
    "GCP": ("gcp", "google cloud", "bigquery", "big query"),
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "scikit-learn": ("scikit-learn", "sklearn", "scikit learn"),
    "TensorFlow": ("tensorflow", "tf", "keras"),
    "PyTorch": ("pytorch", "torch"),
    "R": ("r programming", " r,", "r language"),
    "Java": ("java", "java se", "core java"),
    "JavaScript": ("javascript", "js", "es6", "ecmascript"),
    "TypeScript": ("typescript", "ts"),
    "React": ("react", "react.js", "reactjs", "react 18"),
    "Angular": ("angular", "angularjs"),
    "Vue": ("vue", "vue.js", "vuejs"),
    "Node.js": ("node", "node.js", "nodejs", "express", "express.js"),
    "Django": ("django", "drf", "django rest framework"),
    "FastAPI": ("fastapi",),
    "Flask": ("flask",),
    "Spring Boot": ("spring", "spring boot", "springboot"),
    "PHP": ("php", "laravel"),
    "C++": ("c++", "cpp"),
    "C#": ("c#", "csharp", ".net", "dotnet", "asp.net"),
    "Go": ("golang", "go lang"),
    "PostgreSQL": ("postgres", "postgresql", "psql"),
    "MySQL": ("mysql", "mariadb"),
    "MongoDB": ("mongodb", "mongo", "nosql"),
    "Redis": ("redis",),
    "Elasticsearch": ("elasticsearch", "elastic search", "opensearch"),
    "ETL": ("etl", "elt", "data pipeline", "data pipelines", "ingestion pipeline"),
    "Data Modelling": (
        "data modelling", "data modeling", "dimensional modelling",
        "dimensional modeling", "star schema", "kimball",
    ),
    "Figma": ("figma",),
    "AutoCAD": ("autocad", "auto cad", "cad"),
    "Revit": ("revit",),
    "Primavera": ("primavera", "primavera p6", "p6"),
    "SAP2000": ("sap2000", "sap 2000"),
    "MS Project": ("ms project", "microsoft project"),
}

#: canonical name, lowercased -> canonical
_CANON = {name.lower(): name for name in ALIASES}
#: alias -> canonical
_LOOKUP: dict[str, str] = {}
for _canonical, _spellings in ALIASES.items():
    _LOOKUP[_canonical.lower()] = _canonical
    for _spelling in _spellings:
        _LOOKUP[_spelling.strip().lower()] = _canonical


def canonical(skill: str) -> str:
    """Map one spelling to its canonical name, or tidy it if unknown."""
    key = skill.strip().lower()
    if key in _LOOKUP:
        return _LOOKUP[key]
    # "Python (advanced)" / "SQL - expert" -> try the bare head of the phrase
    head = re.split(r"[(\-–—:,/]", key, maxsplit=1)[0].strip()
    if head and head in _LOOKUP:
        return _LOOKUP[head]
    return skill.strip()


def normalize_all(skills: list[str]) -> list[str]:
    """Canonicalise a skill list, de-duplicated, order preserved."""
    seen: dict[str, None] = {}
    for skill in skills:
        name = canonical(skill)
        if name:
            seen.setdefault(name, None)
    return list(seen)


def mentions(haystack: str, skill: str) -> bool:
    """Does this text demonstrate `skill`, under any of its spellings?

    Word-boundary matched, so "R" does not fire on "React" and "Go" does not fire
    on "Google".
    """
    text = haystack.lower()
    name = canonical(skill)
    candidates = {name.lower(), skill.strip().lower()}
    candidates.update(ALIASES.get(name, ()))

    for token in candidates:
        token = token.strip()
        if not token:
            continue
        if re.search(rf"(?<![a-z0-9+#.]){re.escape(token)}(?![a-z0-9+#])", text):
            return True
    return False

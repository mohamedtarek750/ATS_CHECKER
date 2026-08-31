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
        "rdbms", "relational database", "relational databases",
    ),
    "Python": ("python", "python3", "py"),
    "Power BI": ("power bi", "powerbi", "power-bi", "pbi", "power bi desktop"),
    "Tableau": ("tableau", "tableau desktop"),
    "Excel": ("excel", "ms excel", "microsoft excel", "advanced excel"),
    "Power Query": ("power query", "powerquery", "m query"),
    "Apache Spark": (
        "spark", "apache spark", "pyspark", "spark sql", "spark streaming",
        "structured streaming",
    ),
    "Databricks": ("databricks", "azure databricks"),
    "Airflow": ("airflow", "apache airflow", "mwaa", "composer"),
    "Luigi": ("luigi",),
    "Dagster": ("dagster",),
    "Prefect": ("prefect",),
    "Oozie": ("oozie",),
    "Step Functions": ("step functions", "aws step functions"),
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


# --------------------------------------------------------------------------
# Categories: the "or a comparable X" case
# --------------------------------------------------------------------------
#: Adverts routinely ask for a *kind* of tool rather than a specific one -
#: "Airflow or a comparable orchestrator", "a cloud platform", "a relational
#: database". Matching only the named product fails a candidate who used a
#: different one to do exactly the same job, which is a false negative on
#: somebody qualified: the most expensive mistake an ATS makes.
CATEGORIES: dict[str, tuple[str, ...]] = {
    "orchestrator": (
        "Airflow", "Luigi", "Dagster", "Prefect", "Oozie", "Step Functions",
        "Azure Data Factory",
    ),
    "scheduler": ("Airflow", "Luigi", "Dagster", "Prefect", "Oozie"),
    "workflow": ("Airflow", "Luigi", "Dagster", "Prefect", "Azure Data Factory"),
    "cloud": ("AWS", "Azure", "GCP", "Databricks"),
    "cloud platform": ("AWS", "Azure", "GCP"),
    "relational database": ("SQL", "PostgreSQL", "MySQL"),
    "database": ("SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch"),
    "data warehouse": ("Snowflake", "BigQuery", "Redshift", "Azure"),
    "bi tool": ("Power BI", "Tableau"),
    "dashboarding": ("Power BI", "Tableau"),
    "visualisation": ("Power BI", "Tableau"),
    "visualization": ("Power BI", "Tableau"),
    "streaming": ("Kafka", "Apache Spark"),
    "containerisation": ("Docker", "Kubernetes"),
    "containerization": ("Docker", "Kubernetes"),
    "version control": ("Git",),
    "frontend framework": ("React", "Angular", "Vue"),
    "backend framework": ("Django", "FastAPI", "Flask", "Node.js", "Spring Boot"),
    "deep learning": ("TensorFlow", "PyTorch"),
    "ml framework": ("TensorFlow", "PyTorch", "scikit-learn"),
}

#: Categories are only consulted when the requirement invites a substitute.
SUBSTITUTION_WORDS = (
    "comparable", "similar", "equivalent", "such as", "like ", "or a ", "or an ",
    "any ", "e.g", "for example", "including",
)


def category_members(requirement: str) -> list[str]:
    """Skills that would satisfy `requirement` if it names a category.

    Returns [] unless the wording actually invites a substitute - "React" alone
    must never be satisfied by Angular, and treating every framework mention as a
    category would do exactly that.
    """
    text = requirement.lower()
    if not any(word in text for word in SUBSTITUTION_WORDS):
        return []
    members: list[str] = []
    for name, skills in CATEGORIES.items():
        if name in text:
            members.extend(skills)
    return list(dict.fromkeys(members))


# --------------------------------------------------------------------------
# Implication: using one thing proves another
# --------------------------------------------------------------------------
#: Somebody who wrote PySpark jobs wrote Python, whether or not the word appears.
#: This is the transferable-skill layer: one-directional, and only where the
#: inference is genuinely safe. Django implies Python; Python does not imply
#: Django.
IMPLIES: dict[str, tuple[str, ...]] = {
    "Apache Spark": ("Python",),        # pyspark is the usual route in
    "Pandas": ("Python",),
    "NumPy": ("Python",),
    "scikit-learn": ("Python",),
    "PyTorch": ("Python",),
    "TensorFlow": ("Python",),
    "Django": ("Python",),
    "FastAPI": ("Python",),
    "Flask": ("Python",),
    "Airflow": ("Python",),
    "dbt": ("SQL",),
    "PostgreSQL": ("SQL",),
    "MySQL": ("SQL",),
    "Power BI": ("SQL",),
    "Tableau": ("SQL",),
    "React": ("JavaScript",),
    "Angular": ("TypeScript", "JavaScript"),
    "Vue": ("JavaScript",),
    "Next.js": ("React", "JavaScript"),
    "Node.js": ("JavaScript",),
    "TypeScript": ("JavaScript",),
    "Spring Boot": ("Java",),
    "Kubernetes": ("Docker",),
    "Databricks": ("Apache Spark",),
}


def implied_by(skill: str) -> list[str]:
    """Skills that would prove `skill` without naming it."""
    target = canonical(skill)
    return [source for source, implied in IMPLIES.items() if target in implied]


# --------------------------------------------------------------------------
# Concepts: broad requirements proven by specific work
# --------------------------------------------------------------------------
#: An advert asks for "knowledge of CNNs"; a CV says "DenseNet169, ResNet50,
#: MobileNetV2". Those ARE CNNs - the candidate has demonstrated the requirement
#: more concretely than the word would have. Matching the literal token fails
#: exactly the people who described their work properly.
#:
#: Each entry is: the concept, and the specific things that evidence it. Members
#: prove the concept; the concept does not prove the members. Someone who wrote
#: "machine learning" has not thereby shown XGBoost.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "CNN": (
        "cnn", "convolutional neural network", "convnet",
        "densenet", "resnet", "mobilenet", "inception", "inceptionv3",
        "vgg", "vgg16", "efficientnet", "alexnet", "lenet", "unet", "u-net",
        "xception", "squeezenet",
    ),
    "Machine Learning Algorithms": (
        "random forest", "xgboost", "lightgbm", "catboost", "gradient boosting",
        "decision tree", "svm", "support vector", "knn", "k-nearest",
        "logistic regression", "linear regression", "naive bayes", "k-means",
        "clustering", "ensemble", "adaboost",
    ),
    "Machine Learning": (
        "machine learning", "supervised learning", "unsupervised learning",
        "scikit-learn", "sklearn", "predictive model", "classification model",
        "regression model", "model training",
    ),
    "Deep Learning": (
        "deep learning", "neural network", "tensorflow", "keras", "pytorch",
        "transfer learning", "cnn", "rnn", "lstm", "gru", "transformer",
        "fine-tuning", "fine tuning",
    ),
    "Computer Vision": (
        "computer vision", "opencv", "image classification", "object detection",
        "image segmentation", "yolo", "image processing", "face detection",
        "ocr", "cnn", "image recognition",
    ),
    "NLP": (
        "nlp", "natural language processing", "text classification",
        "sentiment analysis", "named entity", "tokenization", "word2vec",
        "bert", "gpt", "transformer", "spacy", "nltk", "text mining",
        "topic modelling", "topic modeling",
    ),
    "Data Preprocessing": (
        "data preprocessing", "data cleaning", "data cleansing",
        "data transformation", "normalization", "normalisation",
        "standardization", "standardisation", "missing values", "imputation",
        "feature scaling", "outlier", "data wrangling", "feature engineering",
        "one-hot", "encoding",
    ),
    "Model Evaluation": (
        "model evaluation", "accuracy", "precision", "recall", "f1", "f1-score",
        "roc", "auc", "roc-auc", "rmse", "mae", "mse", "confusion matrix",
        "cross-validation", "cross validation", "r2", "r-squared",
    ),
    "Data Visualisation": (
        "data visualisation", "data visualization", "matplotlib", "seaborn",
        "plotly", "power bi", "tableau", "dashboard", "charts",
    ),
    "Statistics": (
        "statistics", "statistical", "hypothesis testing", "a/b test",
        "ab testing", "regression analysis", "probability", "distribution",
        "correlation", "anova", "p-value",
    ),
    "MLOps": (
        "mlops", "mlflow", "model monitoring", "model registry", "kubeflow",
        "model deployment pipeline", "feature store", "model versioning",
        "sagemaker", "vertex ai",
    ),
    "CI/CD": (
        "ci/cd", "cicd", "continuous integration", "continuous deployment",
        "github actions", "jenkins", "gitlab ci", "azure devops", "circleci",
    ),
    "Cloud": (
        "aws", "azure", "gcp", "google cloud", "amazon web services",
        "cloud platform", "ec2", "s3", "lambda", "databricks",
    ),
    "Containerisation": (
        "docker", "kubernetes", "k8s", "container", "containerised",
        "containerized", "helm",
    ),
    "ETL": (
        "etl", "elt", "data pipeline", "ingestion", "airflow", "data flow",
        "batch processing", "data integration",
    ),
    "Big Data": (
        "spark", "pyspark", "hadoop", "hive", "kafka", "distributed processing",
        "big data", "mapreduce", "flink",
    ),
    "Web Development": (
        "react", "angular", "vue", "next.js", "django", "flask", "fastapi",
        "node.js", "express", "rest api", "html", "css",
    ),
    "Databases": (
        "sql", "postgresql", "mysql", "mongodb", "oracle", "sqlite",
        "redis", "database design", "query optimization", "query optimisation",
    ),
    "Version Control": ("git", "github", "gitlab", "bitbucket", "version control"),
    "Agile": ("agile", "scrum", "kanban", "sprint", "jira"),
}

#: Lowercased concept name -> its members, for lookup by requirement text.
_CONCEPT_LOOKUP = {name.lower(): members for name, members in CONCEPTS.items()}

#: Wordings an advert uses for a concept without naming it exactly.
_CONCEPT_ALIASES: dict[str, str] = {
    "cnns": "CNN",
    "convolutional neural networks": "CNN",
    "ml algorithms": "Machine Learning Algorithms",
    "machine learning algorithm": "Machine Learning Algorithms",
    "ml": "Machine Learning",
    "dl": "Deep Learning",
    "cv": "Computer Vision",
    "natural language processing": "NLP",
    "preprocessing": "Data Preprocessing",
    "data pre-processing": "Data Preprocessing",
    "evaluation metrics": "Model Evaluation",
    "model evaluation metrics": "Model Evaluation",
    "model metrics": "Model Evaluation",
    "data viz": "Data Visualisation",
    "visualisation": "Data Visualisation",
    "visualization": "Data Visualisation",
    "cloud platforms": "Cloud",
    "cloud services": "Cloud",
    "containerization": "Containerisation",
    "continuous integration": "CI/CD",
    "big data technologies": "Big Data",
    "relational databases": "Databases",
    "web frameworks": "Web Development",
}


def concept_for(requirement: str) -> str | None:
    """The concept a requirement is asking about, if it is asking about one."""
    text = requirement.strip().lower()
    if text in _CONCEPT_LOOKUP:
        return next(n for n in CONCEPTS if n.lower() == text)
    if text in _CONCEPT_ALIASES:
        return _CONCEPT_ALIASES[text]

    # "Knowledge of CNNs", "Experience with machine learning algorithms".
    for phrase, concept in _CONCEPT_ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", text):
            return concept
    for name in CONCEPTS:
        if re.search(rf"(?<![a-z]){re.escape(name.lower())}(?![a-z])", text):
            return name
    return None


def concept_evidence(concept: str, text: str) -> list[str]:
    """Which members of `concept` this text actually demonstrates."""
    members = CONCEPTS.get(concept, ())
    lowered = text.lower()
    found: list[str] = []
    for member in members:
        # Architectures carry a version: DenseNet169, ResNet50, MobileNetV2.
        # Requiring a non-digit after the name misses every one of them, which is
        # to say it misses candidates who named their models properly. Short
        # tokens like "f1" and "r2" keep the strict boundary so they cannot fire
        # inside an unrelated number.
        # ResNet50, MobileNetV2, InceptionV3 - an optional version suffix.
        trailing = (
            r"(?:[ _-]?v?\d+(?:\.\d+)?)?(?![a-z])"
            if len(member) >= 4 and member[-1].isalpha()
            else r"(?![a-z0-9])"
        )
        if re.search(rf"(?<![a-z0-9]){re.escape(member)}{trailing}", lowered):
            found.append(member)
    return found

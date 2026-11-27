import datetime
import re
from urllib.parse import quote, urlsplit

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.html import escape
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from parsifal.apps.core.models import StoredFile


class Source(models.Model):
    name = models.CharField(max_length=100)
    url = models.CharField(max_length=200)
    is_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Source")
        verbose_name_plural = _("Sources")
        ordering = ("name",)

    def __str__(self):
        return self.name

    def set_url(self, value):
        if "http://" not in value and "https://" not in value and len(value) > 0:
            self.url = "http://{0}".format(value)
        else:
            self.url = value


class Review(models.Model):
    UNPUBLISHED = "U"
    PUBLISHED = "P"
    REVIEW_STATUS = (
        (UNPUBLISHED, "Unpublished"),
        (PUBLISHED, "Published"),
    )

    # Kitchenham & Charters (2007) systematic literature review, Petersen et al. (2015) systematic mapping study, or
    # Cartaxo, Pinto & Soares (2020) rapid review. The type drives which steps are expected (quality assessment is
    # optional for maps and rapid reviews) and the report; what is specific to a rapid review exists only in one.
    SLR = "slr"
    MAPPING = "mapping"
    RAPID = "rapid"
    REVIEW_TYPES = (
        (SLR, _("Systematic literature review")),
        (MAPPING, _("Systematic mapping study")),
        (RAPID, _("Rapid review")),
    )

    # How the demand for a rapid review arose (Cartaxo et al. 2020 §4.1.1; Cartaxo et al. 2018 §7.2).
    DEMAND_PRACTITIONERS = "practitioners"
    DEMAND_AGENDA = "agenda"
    DEMAND_PROSPECTED = "prospected"
    DEMAND_ORGANISATION = "organisation"
    DEMAND_OTHER = "other"
    DEMANDS = (
        (DEMAND_PRACTITIONERS, _("Practitioners asked for it")),
        (DEMAND_AGENDA, _("The researcher aligned their agenda with practitioners' needs")),
        (DEMAND_PROSPECTED, _("The researcher prospected a practical problem")),
        (DEMAND_ORGANISATION, _("Policy makers or the organisation asked for it")),
        (DEMAND_OTHER, _("Other")),
    )

    name = models.SlugField(_("name"), max_length=255)
    title = models.CharField(_("title"), max_length=255)
    description = models.CharField(_("description"), max_length=500, blank=True)
    author = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name=_("author"))
    create_date = models.DateTimeField(_("date created"), auto_now_add=True)
    last_update = models.DateTimeField(_("last update"), auto_now=True)
    objective = models.TextField(_("objective"), max_length=1000, blank=True)
    sources = models.ManyToManyField(Source, verbose_name=_("sources"))
    status = models.CharField(_("status"), max_length=1, choices=REVIEW_STATUS, default=UNPUBLISHED)
    co_authors = models.ManyToManyField(User, related_name="co_authors", verbose_name=_("co-authors"))
    quality_assessment_cutoff_score = models.FloatField(_("quality assessment cutoff score"), default=0.0)
    population = models.CharField(_("population"), max_length=200, blank=True)
    intervention = models.CharField(_("intervention"), max_length=200, blank=True)
    comparison = models.CharField(_("comparison"), max_length=200, blank=True)
    outcome = models.CharField(_("outcome"), max_length=200, blank=True)
    context = models.CharField(_("context"), max_length=200, blank=True)
    review_type = models.CharField(_("review type"), max_length=10, choices=REVIEW_TYPES, default=SLR)
    # Protocol sections recommended by the guidelines but not modelled upstream (K 5.4, P 5.1.5)
    selection_procedure = models.TextField(_("study selection procedure"), blank=True)
    # How the inclusion criteria combine: a study must meet all of them, or at least one (Include and Screen with AI
    # read it; each run keeps the rule it used).
    INCLUDE_ALL = "all"
    INCLUDE_ANY = "any"
    INCLUSION_RULES = (
        (INCLUDE_ALL, _("all inclusion criteria")),
        (INCLUDE_ANY, _("at least one inclusion criterion")),
    )
    inclusion_rule = models.CharField(
        _("a study must meet"), max_length=3, choices=INCLUSION_RULES, default=INCLUDE_ALL
    )
    synthesis_strategy = models.TextField(_("synthesis strategy"), blank=True)
    validity_threats = models.TextField(_("validity threats"), blank=True)
    # PRISMA flow diagram: the exclusion criterion that means "full text not retrieved" (a study rejected at the
    # full text with it counts as a report not retrieved, not as one excluded).
    prisma_not_retrieved = models.ForeignKey(
        "SelectionCriteria", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # The practical context of a rapid review (Cartaxo et al. 2020 §4.1): why it was asked for, the problem as defined
    # with the practitioners, their context, who takes part and how, and its time frame (days or weeks).
    demand = models.CharField(_("demand"), max_length=20, choices=DEMANDS, blank=True)
    demand_notes = models.TextField(_("how the demand arose"), blank=True)
    practical_problem = models.TextField(_("practical problem"), blank=True)
    practical_context = models.TextField(_("practical context"), blank=True)
    stakeholder_roles = models.TextField(_("stakeholders and their roles"), blank=True)
    started_on = models.DateField(_("start date"), null=True, blank=True)
    deadline = models.DateField(_("deadline"), null=True, blank=True)
    # The prefixes of the codes the review numbers its research questions, criteria, quality questions and data
    # extraction fields with (services.codes): {"question": "QP", …}; what is left out takes the default (RQ, IC…).
    code_prefixes = models.JSONField(_("code prefixes"), default=dict, blank=True)

    class Meta:
        verbose_name = _("review")
        verbose_name_plural = _("reviews")
        unique_together = (("name", "author"),)

    def __str__(self):
        return self.name

    @property
    def is_mapping_study(self):
        return self.review_type == self.MAPPING

    @property
    def is_rapid_review(self):
        """The switch for everything specific to a rapid review (Cartaxo et al. 2020)."""
        return self.review_type == self.RAPID

    def stages(self):
        """
        The screening rounds of the review, in order (StudyDecision stages): a rapid review starts with a round on
        the titles only (Cartaxo et al. 2020 §4.2.2); the others with the titles and abstracts.
        """
        if self.is_rapid_review:
            return [StudyDecision.TITLE, StudyDecision.TITLE_ABSTRACT, StudyDecision.FULL_TEXT]
        return [StudyDecision.TITLE_ABSTRACT, StudyDecision.FULL_TEXT]

    def stage_choices(self):
        labels = dict(StudyDecision.STAGES)
        return [(stage, labels[stage]) for stage in self.stages()]

    @property
    def first_stage(self):
        return self.stages()[0]

    def get_absolute_url(self):
        return reverse("review", args=(self.author.username, self.name))

    def get_questions(self):
        questions = Question.objects.filter(review__id=self.id)
        return questions

    def get_inclusion_criterias(self):
        return SelectionCriteria.objects.filter(review__id=self.id, criteria_type="I")

    def get_exclusion_criterias(self):
        return SelectionCriteria.objects.filter(review__id=self.id, criteria_type="E")

    def get_keywords(self):
        return Keyword.objects.filter(review__id=self.id, synonym_of=None)

    def is_author_or_coauthor(self, user):
        if user.id == self.author.id:
            return True
        for co_author in self.co_authors.all():
            if user.id == co_author.id:
                return True
        return False

    def get_generic_search_string(self):
        try:
            search_string = SearchSession.objects.filter(review__id=self.id, source=None)[:1].get()
        except SearchSession.DoesNotExist:
            search_string = SearchSession(review=self)
        return search_string

    def get_latest_source_search_strings(self):
        return self.searchsession_set.exclude(source=None).order_by("source__name")

    def get_source_articles(self, source_id=None):
        queryset = Article.objects.filter(review__id=self.id).select_related(
            "created_by__profile", "starred_by__profile"
        )

        if source_id is not None:
            queryset = queryset.filter(source__id=source_id)
        return queryset

    def get_duplicate_articles(self):
        articles = Article.objects.filter(review__id=self.id).exclude(status=Article.DUPLICATED).order_by("title")
        grouped_articles = dict()

        for article in articles:
            slug = slugify(article.title)
            if slug not in grouped_articles.keys():
                grouped_articles[slug] = {"size": 0, "articles": list()}
            grouped_articles[slug]["size"] += 1
            grouped_articles[slug]["articles"].append(article)

        duplicates = list()
        for slug, data in grouped_articles.items():
            if data["size"] > 1:
                duplicates.append(data["articles"])

        return duplicates

    def get_accepted_articles(self):
        return Article.objects.filter(review__id=self.id, status=Article.ACCEPTED)

    def get_final_selection_articles(self):
        accepted_articles = Article.objects.filter(review__id=self.id, status=Article.ACCEPTED).annotate(
            score=Coalesce(Sum("qualityassessment__answer__weight"), Value(0.0))
        )
        if self.has_quality_assessment_checklist() and self.quality_assessment_cutoff_score > 0.0:
            accepted_articles = accepted_articles.filter(score__gt=self.quality_assessment_cutoff_score)
        return accepted_articles

    def has_quality_assessment_checklist(self):
        has_questions = self.qualityquestion_set.exists()
        has_answers = self.qualityanswer_set.exists()
        return has_questions and has_answers

    def get_data_extraction_fields(self):
        return DataExtractionField.objects.filter(review__id=self.id)

    def get_quality_assessment_questions(self):
        return QualityQuestion.objects.filter(review__id=self.id)

    def get_quality_assessment_answers(self):
        return QualityAnswer.objects.filter(review__id=self.id)

    def calculate_quality_assessment_max_score(self):
        try:
            questions_count = QualityQuestion.objects.filter(review__id=self.id).count()
            higher_weight_answer = QualityAnswer.objects.filter(review__id=self.id).order_by("-weight")[:1].get()
            if questions_count and higher_weight_answer:
                return questions_count * higher_weight_answer.weight
            else:
                return 0.0
        except Exception:
            return 0.0


class Question(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="research_questions")
    question = models.CharField(max_length=500)
    parent_question = models.ForeignKey("self", on_delete=models.CASCADE, null=True, related_name="+")
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Question"
        verbose_name_plural = "Questions"
        ordering = ("order",)

    def __str__(self):
        return self.question

    def get_child_questions(self):
        return Question.objects.filter(parent_question=self)


class SelectionCriteria(models.Model):
    INCLUSION = "I"
    EXCLUSION = "E"
    SELECTION_TYPES = (
        (INCLUSION, "Inclusion"),
        (EXCLUSION, "Exclusion"),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    criteria_type = models.CharField(max_length=1, choices=SELECTION_TYPES)
    description = models.CharField(max_length=200)
    # Its place among the review's criteria of its type: it gives the criterion its code (IC1, EC2…; services.codes).
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Selection Criteria"
        verbose_name_plural = "Selection Criterias"
        ordering = ("order", "pk")

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        self.description = self.description[:200]
        super().save(*args, **kwargs)


class SearchSession(models.Model):
    DATABASE = "database"
    SNOWBALLING = "snowballing"
    MANUAL = "manual"
    OTHER = "other"
    SEARCH_TYPES = (
        (DATABASE, _("Database search")),
        (SNOWBALLING, _("Snowballing")),
        (MANUAL, _("Manual search")),
        (OTHER, _("Other")),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, null=True)
    search_string = models.TextField(max_length=10000)
    version = models.IntegerField(default=1)
    # Search documentation (Kitchenham 6.1.4 Table 2; Petersen 5.1.2)
    search_type = models.CharField(_("search type"), max_length=12, choices=SEARCH_TYPES, default=DATABASE)
    searched_at = models.DateField(_("date of search"), null=True, blank=True)
    years_from = models.IntegerField(_("years covered (from)"), null=True, blank=True)
    years_to = models.IntegerField(_("years covered (to)"), null=True, blank=True)
    result_count = models.IntegerField(_("number of results"), null=True, blank=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("review", "source"), name="unique_search_session_per_source"),
            models.UniqueConstraint(
                fields=("review",), condition=Q(source__isnull=True), name="unique_generic_search_session"
            ),
        )

    def __str__(self):
        return self.search_string

    def search_string_as_html(self):
        escaped_string = escape(self.search_string)
        html = escaped_string.replace(" OR ", " <strong>OR</strong> ").replace(" AND ", " <strong>AND</strong> ")
        return html


def search_result_file_upload_to(instance, filename):
    """Kept only because historical migration 0020 references it; the SearchResult model was removed."""
    return "reviews/{0}/search_result/".format(instance.review.pk)


class Article(models.Model):
    UNCLASSIFIED = "U"
    REJECTED = "R"
    ACCEPTED = "A"
    DUPLICATED = "D"
    ARTICLE_STATUS = (
        (UNCLASSIFIED, "Unclassified"),
        (REJECTED, "Rejected"),
        (ACCEPTED, "Accepted"),
        (DUPLICATED, "Duplicated"),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    bibtex_key = models.CharField(max_length=100)
    title = models.CharField(max_length=1000, null=True, blank=True, db_index=True)
    author = models.CharField(max_length=1000, null=True, blank=True)
    journal = models.CharField(max_length=1000, null=True, blank=True)
    year = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    year_int = models.IntegerField(_("year (numeric)"), null=True, blank=True, db_index=True, editable=False)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, null=True)
    pages = models.CharField(max_length=20, null=True, blank=True)
    volume = models.CharField(max_length=100, null=True, blank=True)
    abstract = models.TextField(max_length=4000, null=True, blank=True)
    document_type = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=1, choices=ARTICLE_STATUS, default=UNCLASSIFIED)
    comments = models.TextField(max_length=2000, null=True, blank=True)
    doi = models.CharField(max_length=50, null=True, blank=True)
    url = models.CharField(max_length=500, null=True, blank=True)
    affiliation = models.CharField(max_length=500, null=True, blank=True)
    author_keywords = models.CharField(max_length=500, null=True, blank=True)
    keywords = models.CharField(max_length=500, null=True, blank=True)
    publisher = models.CharField(max_length=100, null=True, blank=True)
    issn = models.CharField(max_length=50, null=True, blank=True)
    language = models.CharField(max_length=50, null=True, blank=True)
    note = models.CharField(max_length=500, null=True, blank=True)
    finished_data_extraction = models.BooleanField(default=False)
    selection_criteria = models.ForeignKey(SelectionCriteria, null=True, blank=True, on_delete=models.SET_NULL)
    found_via = models.ForeignKey(
        SearchSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="found_articles",
        verbose_name=_("found via search"),
    )
    # The study's full text, any status may have one. Attaching it leaves updated_by alone: that says who set the
    # status, which AI screening relies on.
    pdf = models.OneToOneField(
        StoredFile, null=True, blank=True, related_name="article", on_delete=models.SET_NULL, verbose_name="PDF"
    )
    # Starred in this review: one mark per study, shared by every member (people and agents), whatever its status.
    # Who starred it and when are kept for the record; like the PDF, it leaves updated_by alone.
    starred_at = models.DateTimeField(_("starred at"), null=True, blank=True)
    starred_by = models.ForeignKey(
        User, null=True, blank=True, related_name="+", on_delete=models.SET_NULL, verbose_name=_("starred by")
    )
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, related_name="articles_created", on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="articles_updated", on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"

    def __str__(self):
        return self.title

    @staticmethod
    def parse_year(value):
        """Extract a four-digit year from the free-text BibTeX year field, or None."""
        match = re.search(r"\d{4}", value or "")
        return int(match.group()) if match else None

    def save(self, *args, **kwargs):
        self.year_int = self.parse_year(self.year)
        super().save(*args, **kwargs)

    @property
    def starred(self):
        return self.starred_at is not None

    @property
    def external_url(self):
        """
        Where the study window's External Link goes: the study's URL, or else its DOI at doi.org; None when it has
        neither. Only http(s) URLs count, so a ``javascript:`` URL from an imported file never becomes a link.
        """
        url = (self.url or "").strip()
        if urlsplit(url).scheme.lower() in ("http", "https"):
            return url
        return self.doi_url

    @property
    def doi_url(self):
        """The study's DOI at doi.org, or None."""
        from parsifal.apps.reviews.services.studies import clean_doi  # the services import this module

        doi = clean_doi(self.doi)
        return f"https://doi.org/{quote(doi, safe='/:;()[]._-')}" if doi else None

    @property
    def ai_score(self):
        """How likely the study is relevant, by the latest AI run that answered about it (0–1), or None."""
        from parsifal.apps.reviews.services.ai_screening import article_relevance  # the services import this module

        return article_relevance(self)

    @property
    def ai_score_label(self):
        """Which action gave ``ai_score``, when the study came annotated (``ai_screening.with_relevance``)."""
        from parsifal.apps.reviews.services.ai_screening import LABELS

        return LABELS.get(getattr(self, "ai_phase", None) or "", "")

    def access_url(self, proxy):
        """
        Where the study window's Via CAPES link goes for a user whose library proxy is ``proxy`` (Settings → Library
        access; ``core.library_proxy``): the DOI through the proxy, which reaches the publisher's page, or else the
        study's URL through it; None without a proxy or when neither can go through it.
        """
        from parsifal.apps.core import library_proxy

        if not proxy:
            return None
        if self.doi_url:
            return library_proxy.proxied(self.doi_url, proxy)
        return library_proxy.proxied(self.url, proxy)

    def get_score(self):
        score = QualityAssessment.objects.filter(article__id=self.id).aggregate(Sum("answer__weight"))
        if score["answer__weight__sum"] is None:
            return 0.0
        return score["answer__weight__sum"]

    def get_quality_assesment(self):
        quality_assessments = QualityAssessment.objects.filter(article__id=self.id)
        return quality_assessments

    def get_status_html(self):
        label = {
            Article.UNCLASSIFIED: "default",
            Article.REJECTED: "danger",
            Article.ACCEPTED: "success",
            Article.DUPLICATED: "warning",
        }
        return '<span class="label label-{0}">{1}</span>'.format(label[self.status], self.get_status_display())


@receiver(post_delete, sender=Article)
def delete_article_pdf(sender, instance, **kwargs):
    """The full text goes with its study (also when its source or the whole review is deleted)."""
    if instance.pdf_id:
        StoredFile.objects.filter(pk=instance.pdf_id).delete()


class Keyword(models.Model):
    POPULATION = "P"
    INTERVENTION = "I"
    COMPARISON = "C"
    OUTCOME = "O"
    RELATED_TO = (
        (POPULATION, "Population"),
        (INTERVENTION, "Intervention"),
        (COMPARISON, "Comparison"),
        (OUTCOME, "Outcome"),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="keywords")
    description = models.CharField(max_length=200)
    synonym_of = models.ForeignKey("self", on_delete=models.CASCADE, null=True, related_name="synonyms")
    related_to = models.CharField(max_length=1, choices=RELATED_TO, blank=True)

    class Meta:
        verbose_name = "Keyword"
        verbose_name_plural = "Keywords"
        ordering = ("description",)

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        self.description = self.description[:200]
        super().save(*args, **kwargs)

    def get_synonyms(self):
        return Keyword.objects.filter(review__id=self.review.id, synonym_of__id=self.id)


class QualityAnswer(models.Model):
    SUGGESTED_ANSWERS = (("Yes", 1.0), ("Partially", 0.5), ("No", 0.0))

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    weight = models.FloatField()

    class Meta:
        verbose_name = "Quality Assessment Answer"
        verbose_name_plural = "Quality Assessment Answers"
        ordering = ("-weight",)

    def __str__(self):
        return self.description


class QualityQuestion(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Quality Assessment Question"
        verbose_name_plural = "Quality Assessment Questions"
        ordering = ("order",)

    def __str__(self):
        return self.description


class QualityAssessment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    question = models.ForeignKey(QualityQuestion, on_delete=models.CASCADE)
    answer = models.ForeignKey(QualityAnswer, on_delete=models.CASCADE, null=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("article", "question"), name="unique_quality_assessment_per_question"),
        )

    def __str__(self):
        return str(self.article.id) + " " + str(self.question.id)


class DataExtractionField(models.Model):
    BOOLEAN_FIELD = "B"
    STRING_FIELD = "S"
    FLOAT_FIELD = "F"
    INTEGER_FIELD = "I"
    DATE_FIELD = "D"
    SELECT_ONE_FIELD = "O"
    SELECT_MANY_FIELD = "M"
    FIELD_TYPES = (
        (BOOLEAN_FIELD, "Boolean Field"),
        (STRING_FIELD, "String Field"),
        (FLOAT_FIELD, "Float Field"),
        (INTEGER_FIELD, "Integer Field"),
        (DATE_FIELD, "Date Field"),
        (SELECT_ONE_FIELD, "Select One Field"),
        (SELECT_MANY_FIELD, "Select Many Field"),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    field_type = models.CharField(max_length=1, choices=FIELD_TYPES)
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Data Extraction Field"
        verbose_name_plural = "Data Extraction Fields"
        ordering = ("order",)

    def get_select_values(self):
        return DataExtractionLookup.objects.filter(field__id=self.id)

    def is_select_field(self):
        return self.field_type in (self.SELECT_ONE_FIELD, self.SELECT_MANY_FIELD)


class DataExtractionLookup(models.Model):
    field = models.ForeignKey(DataExtractionField, on_delete=models.CASCADE)
    value = models.CharField(max_length=1000)

    class Meta:
        verbose_name = "Lookup Value"
        verbose_name_plural = "Lookup Values"
        ordering = ("value",)

    def __str__(self):
        return self.value


class DataExtraction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    field = models.ForeignKey(DataExtractionField, on_delete=models.CASCADE)
    value = models.TextField(blank=True, null=True)
    select_values = models.ManyToManyField(DataExtractionLookup)
    # Where the study supports the value: the passage, its page, the figure or table. A study's extraction is done
    # only when every value it has comes with its evidence, so that anyone can check it later.
    evidence = models.TextField(_("evidence"), blank=True)

    class Meta:
        constraints = (models.UniqueConstraint(fields=("article", "field"), name="unique_data_extraction_per_field"),)

    def _set_boolean_value(self, value):
        if value:
            if value in ["True", "False"]:
                self.value = value
            else:
                raise ValueError('Expected values: "True" or "False"')
        else:
            self.value = ""

    def _set_string_value(self, value):
        self.value = value.strip()

    def _set_float_value(self, value):
        try:
            if value:
                _value = value.replace(",", ".")
                self.value = float(_value)
            else:
                self.value = ""
        except Exception:
            raise Exception(
                "Invalid input for "
                + self.field.description
                + " field. Expected value: floating point number. Please use dot instead of comma."
            )

    def _set_integer_value(self, value):
        try:
            if value:
                _value = value.replace(",", ".")
                self.value = int(float(_value))
            else:
                self.value = ""
        except Exception:
            raise Exception("Invalid input for " + self.field.description + " field. Expected value: integer number.")

    def _set_date_value(self, value):
        try:
            if value:
                _value = datetime.datetime.strptime(value, "%m/%d/%Y").date()
                self.value = str(_value)
            else:
                self.value = ""
        except Exception:
            raise Exception(
                "Invalid input for "
                + self.field.description
                + " field. Expected value: date. Please use the format MM/DD/YYYY."
            )

    def _set_select_one_value(self, value):
        self.value = ""
        self.select_values.clear()
        if value:
            _value = DataExtractionLookup.objects.get(pk=value)
            self.select_values.add(_value)

    def _set_select_many_value(self, value):
        self.value = ""
        _value = DataExtractionLookup.objects.get(pk=value)
        if _value in self.select_values.all():
            self.select_values.remove(_value)
        else:
            self.select_values.add(_value)

    def set_value(self, value):
        set_value_functions = {
            DataExtractionField.BOOLEAN_FIELD: self._set_boolean_value,
            DataExtractionField.STRING_FIELD: self._set_string_value,
            DataExtractionField.FLOAT_FIELD: self._set_float_value,
            DataExtractionField.INTEGER_FIELD: self._set_integer_value,
            DataExtractionField.DATE_FIELD: self._set_date_value,
            DataExtractionField.SELECT_ONE_FIELD: self._set_select_one_value,
            DataExtractionField.SELECT_MANY_FIELD: self._set_select_many_value,
        }
        set_value_functions[self.field.field_type](value[:1000])

    def _get_boolean_value(self):
        try:
            if self.value == "True":
                return True
            elif self.value == "False":
                return False
            else:
                return ""
        except Exception:
            return ""

    def _get_string_value(self):
        return self.value

    def _get_float_value(self):
        try:
            return float(self.value)
        except Exception:
            return ""

    def _get_integer_value(self):
        try:
            return int(self.value)
        except Exception:
            return ""

    def _get_date_value(self):
        try:
            if self.value != "":
                return datetime.datetime.strptime(self.value, "%Y-%m-%d").date()
            else:
                return ""
        except Exception:
            return ""

    def _get_select_one_value(self):
        try:
            return self.select_values.all()[0]
        except Exception:
            return None

    def _get_select_many_value(self):
        try:
            return self.select_values.all()
        except Exception:
            return []

    def get_value(self):
        if self.field.field_type:
            get_value_functions = {
                DataExtractionField.BOOLEAN_FIELD: self._get_boolean_value,
                DataExtractionField.STRING_FIELD: self._get_string_value,
                DataExtractionField.FLOAT_FIELD: self._get_float_value,
                DataExtractionField.INTEGER_FIELD: self._get_integer_value,
                DataExtractionField.DATE_FIELD: self._get_date_value,
                DataExtractionField.SELECT_ONE_FIELD: self._get_select_one_value,
                DataExtractionField.SELECT_MANY_FIELD: self._get_select_many_value,
            }
            return get_value_functions[self.field.field_type]()
        return self._get_string_value()

    def get_date_value_as_string(self):
        try:
            value = self.get_value()
            return value.strftime("%m/%d/%Y")
        except Exception:
            return ""


# ---------------------------------------------------------------------------------------------------------------------
# Systematic mapping studies (Petersen et al. 2015)
# ---------------------------------------------------------------------------------------------------------------------


class ReviewTestSetArticle(models.Model):
    """A known relevant paper used to evaluate the search (Petersen 5.1.2 'paper test-set')."""

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="test_set")
    title = models.CharField(_("title"), max_length=1000)
    doi = models.CharField(_("DOI"), max_length=100, blank=True)
    notes = models.CharField(_("notes"), max_length=500, blank=True)
    matched_article = models.ForeignKey(
        Article, null=True, blank=True, on_delete=models.SET_NULL, related_name="test_set_matches"
    )

    class Meta:
        verbose_name = _("test-set article")
        verbose_name_plural = _("test-set articles")
        ordering = ("pk",)

    def __str__(self):
        return self.title


class ProcessChecklistItem(models.Model):
    """One of the actions of Petersen et al. (2015) Table 8, used to self-assess the mapping process."""

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="checklist_items")
    key = models.CharField(_("action"), max_length=50)
    applied = models.BooleanField(default=False)
    notes = models.CharField(_("notes"), max_length=500, blank=True)

    class Meta:
        verbose_name = _("process checklist item")
        verbose_name_plural = _("process checklist items")
        constraints = (models.UniqueConstraint(fields=("review", "key"), name="unique_checklist_item_per_review"),)

    def __str__(self):
        return self.key


# ---------------------------------------------------------------------------------------------------------------------
# Reporting: threats to validity
# ---------------------------------------------------------------------------------------------------------------------


class ValidityThreat(models.Model):
    """
    A threat to the validity of the review and what was done about it (Petersen et al. 2015 §3.6 and §5.1.5, after
    Petersen & Gencel 2013; Kitchenham & Charters 2007 §7, the strengths and weaknesses of the review). Its type is
    free: the suggestions (services.threats) follow those schemes, and a review may use any other.
    """

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="threats")
    category = models.CharField(_("type"), max_length=100, blank=True)
    title = models.CharField(_("name"), max_length=255)
    description = models.TextField(_("description"), blank=True)
    mitigation = models.TextField(_("mitigation"), blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("threat to validity")
        verbose_name_plural = _("threats to validity")
        ordering = ("order", "pk")

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------------------------------------------------
# Reporting: the manuscripts written from the review, each with its versions
# ---------------------------------------------------------------------------------------------------------------------


class Manuscript(models.Model):
    """
    A text written from the review — the paper, a short or an extended version of it, the same paper in another
    template, a report for practitioners — named as the review likes. Each file uploaded to it is a new version; none
    replaces another (services.manuscripts).
    """

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="manuscripts")
    name = models.CharField(_("name"), max_length=100)
    # What sets it apart: its template, venue, length...
    description = models.CharField(_("description"), max_length=500, blank=True)
    order = models.IntegerField(default=0)
    # The number of the latest version uploaded, deleted or not: a number is never given twice.
    last_version = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("manuscript")
        verbose_name_plural = _("manuscripts")
        ordering = ("order", "pk")
        constraints = (models.UniqueConstraint(fields=("review", "name"), name="unique_manuscript_name_per_review"),)

    def __str__(self):
        return self.name


class ManuscriptVersion(models.Model):
    """One version of a manuscript: its file (a PDF, a Word or OpenDocument text, LaTeX) and what changed in it."""

    manuscript = models.ForeignKey(Manuscript, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField(_("version"))
    file = models.OneToOneField(StoredFile, on_delete=models.CASCADE, related_name="manuscript_version")
    notes = models.CharField(_("notes"), max_length=500, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("manuscript version")
        verbose_name_plural = _("manuscript versions")
        ordering = ("-number",)
        constraints = (
            models.UniqueConstraint(fields=("manuscript", "number"), name="unique_version_number_per_manuscript"),
        )

    def __str__(self):
        return f"{self.manuscript.name} v{self.number}"

    @property
    def is_pdf(self):
        return self.file.content_type == "application/pdf"


@receiver(post_delete, sender=ManuscriptVersion)
def delete_manuscript_version_file(sender, instance, **kwargs):
    """The file goes with its version (also when the manuscript or the whole review is deleted)."""
    StoredFile.objects.filter(pk=instance.file_id).delete()


# ---------------------------------------------------------------------------------------------------------------------
# Multi-reviewer study selection (Kitchenham 6.2.3, Petersen 5.1.2)
# ---------------------------------------------------------------------------------------------------------------------


class StudyDecision(models.Model):
    """
    One reviewer's (human or agent) decision about one article at one screening stage. ``Article.status``
    remains the consolidated decision; these rows make independent screening and agreement measures possible.
    """

    TITLE = "title"  # rapid reviews only: a first round on the titles (Cartaxo et al. 2020 §4.2.2)
    TITLE_ABSTRACT = "title_abstract"
    FULL_TEXT = "full_text"
    STAGES = (
        (TITLE, _("Title screening")),
        (TITLE_ABSTRACT, _("Title and abstract screening")),
        (FULL_TEXT, _("Full-text screening")),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="decisions")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="decisions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_decisions")
    stage = models.CharField(_("stage"), max_length=20, choices=STAGES, default=TITLE_ABSTRACT)
    status = models.CharField(_("decision"), max_length=1, choices=Article.ARTICLE_STATUS)
    selection_criteria = models.ForeignKey(SelectionCriteria, null=True, blank=True, on_delete=models.SET_NULL)
    comments = models.TextField(_("comments"), max_length=2000, blank=True)
    decided_at = models.DateTimeField(auto_now=True)
    # The AI screening run that made this decision; empty when the reviewer made it (or before runs were linked).
    # Undoing the run restores the decisions that are still its own.
    run = models.ForeignKey("ScreeningRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="decisions")

    class Meta:
        verbose_name = _("study decision")
        verbose_name_plural = _("study decisions")
        ordering = ("article_id", "stage", "user_id")
        constraints = (
            models.UniqueConstraint(fields=("article", "user", "stage"), name="unique_decision_per_reviewer_stage"),
        )

    def __str__(self):
        return f"{self.user.username}: {self.get_status_display()} ({self.get_stage_display()})"


class ReviewAgent(models.Model):
    """
    An AI agent that works on one review as a co-author, with an account of its own so that everything it does is
    attributed to it. The account belongs to the review: deleting the agent (or the review) deletes the account,
    its tokens and everything stored under it.
    """

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="agents")
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="agent_of")
    name = models.CharField(_("name"), max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("review agent")
        verbose_name_plural = _("review agents")
        ordering = ("created_at", "pk")

    def __str__(self):
        return f"{self.name} ({self.user.username})"


@receiver(post_delete, sender=ReviewAgent)
def delete_agent_account(sender, instance, **kwargs):
    """The agent's account never outlives its place in the review (also when the whole review is deleted)."""
    User.objects.filter(pk=instance.user_id).delete()


class ScreeningRun(models.Model):
    """
    One AI screening of study selection — by exclusion criteria, by inclusion criteria, or both in one go (Screen with
    AI) — in no particular order: what was sent to the model, its progress and how it ended. The decisions are
    recorded as ``reviewer``, chosen when the run starts; deleting that account deletes its runs with its decisions.
    """

    EXCLUSION = "exclusion"
    INCLUSION = "inclusion"
    SCREEN = "screen"
    RETENTION = "retention"
    # The action of the run (named "phase" in the code and the API, though the actions have no order).
    PHASES = (
        (EXCLUSION, _("Exclude with AI")),  # rejects a study when one exclusion criterion applies
        (INCLUSION, _("Include with AI")),  # accepts a study when the inclusion criteria are met (all, or one)
        (SCREEN, _("Screen with AI")),  # both questions in one request: rejects, accepts or leaves undecided
        (RETENTION, _("Retain with AI")),  # removed; its runs remain in the history
    )

    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"
    STATUSES = (
        (RUNNING, _("Running")),  # also while interrupted: it can be continued
        (FINISHED, _("Finished")),
        (CANCELLED, _("Discarded")),  # a new run was started before this one finished
        (FAILED, _("Failed")),  # runs from before runs could be continued
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="screening_runs")
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="screening_runs")
    started_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    phase = models.CharField(_("phase"), max_length=10, choices=PHASES, default=EXCLUSION)
    model = models.CharField(_("model"), max_length=100)
    # Snapshot of what was sent: review context, extra guidance, the criteria of the phase (key, id, description),
    # threshold and scope. The criteria may change later; the snapshot says what Jev saw. (Inclusion runs made
    # before Include with AI stopped rejecting kept accept_threshold and reject_threshold instead of threshold.)
    parameters = models.JSONField(_("parameters"), default=dict)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=RUNNING)
    total = models.PositiveIntegerField(_("studies to screen"), default=0)
    # Why the run is waiting (Jev refused the key or was unavailable); cleared by the next step that works.
    error = models.CharField(_("error"), max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # When a step last ran: a running run without steps for a while was interrupted and can be continued.
    last_step_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Whether its results keep what each study and decision was like before (see ScreeningResult), so it can be
    # undone. Runs made before Parsifal kept that cannot.
    undoable = models.BooleanField(_("can be undone"), default=True)

    class Meta:
        verbose_name = _("screening run")
        verbose_name_plural = _("screening runs")
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"Screening run {self.pk} ({self.get_status_display()})"


class ScreeningResult(models.Model):
    """What the model answered for one study in a run, kept for audit whether or not the study was rejected."""

    PENDING = "pending"
    EXCLUDED = "excluded"
    PASSED = "passed"
    INCLUDED = "included"
    UNDECIDED = "undecided"
    ERROR = "error"
    OUTCOMES = (
        (PENDING, _("Pending")),
        (EXCLUDED, _("Excluded")),  # exclusion: rejected with a criterion; retention: not retained, rejected
        (PASSED, _("Passed to the next phase")),  # exclusion: no exclusion criterion applies
        (INCLUDED, _("Included")),  # inclusion: every inclusion criterion is met; retention: retained, accepted
        (UNDECIDED, _("Undecided")),  # inclusion: not every inclusion criterion is clearly met; left to the reviewers
        (ERROR, _("Error")),
    )

    run = models.ForeignKey(ScreeningRun, on_delete=models.CASCADE, related_name="results")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="screening_results")
    # Status of the study when the run took it. The run only changes the study if it still has this status.
    previous_status = models.CharField(_("status before the run"), max_length=1, blank=True)
    outcome = models.CharField(_("outcome"), max_length=10, choices=OUTCOMES, default=PENDING)
    # Exclusion: the probability that some exclusion criterion applies. Inclusion never rejects and leaves it empty.
    p_exclude = models.FloatField(_("probability used to reject"), null=True, blank=True)
    # Inclusion: the lowest probability that an inclusion criterion is met (every criterion must be met). Retention:
    # the probability that the study should be retained for full-text assessment.
    p_include = models.FloatField(_("lowest probability that an inclusion criterion is met"), null=True, blank=True)
    # Exclusion: {option: p}. Inclusion: {criterion key: p(meets)}, the probability of yes of its question.
    # Retention: {"retain": p}.
    probabilities = models.JSONField(_("probability of each option"), null=True, blank=True)
    selection_criteria = models.ForeignKey(SelectionCriteria, null=True, blank=True, on_delete=models.SET_NULL)
    model = models.CharField(_("model version that answered"), max_length=100, blank=True)
    error = models.CharField(_("error"), max_length=500, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    # What undoing the run restores. The status the run gave the study ("" when it left the study as it was) and, when
    # it changed it, the study's criterion and last editor before (its status before is ``previous_status``); the
    # run's change is still in place while the study has that status, the run's reviewer as last editor and
    # ``processed_at`` as its last change.
    status_set = models.CharField(_("status the run gave the study"), max_length=1, blank=True)
    previous_criteria = models.ForeignKey(
        SelectionCriteria, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    previous_updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    previous_updated_at = models.DateTimeField(null=True, blank=True)
    # The reviewer's decision the run replaced: {status, criteria_id, comments, decided_at, run_id}, or None when there
    # was none (then undoing removes the run's decision).
    previous_decision = models.JSONField(_("reviewer's decision before the run"), null=True, blank=True)

    class Meta:
        verbose_name = _("screening result")
        verbose_name_plural = _("screening results")
        ordering = ("run_id", "pk")
        constraints = (models.UniqueConstraint(fields=("run", "article"), name="unique_screening_result_per_run"),)

    def __str__(self):
        return f"{self.article_id}: {self.get_outcome_display()}"


class ReviewBackup(models.Model):
    """
    A backup of one review kept on the server: everything of it in one .tar.gz (see services.review_backups), which
    can be downloaded, restored over the review or imported as a new review.
    """

    UPLOADED = "Uploaded"  # the note of a backup file added to the list (taken elsewhere, or downloaded before)

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="backups")
    file = models.OneToOneField(StoredFile, on_delete=models.CASCADE, related_name="review_backup")
    note = models.CharField(_("note"), max_length=200, blank=True)  # e.g. taken before a restore, or uploaded
    studies = models.PositiveIntegerField(_("studies"), default=0)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("review backup")
        verbose_name_plural = _("review backups")
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return self.file.filename

    @property
    def uploaded(self):
        return self.note == self.UPLOADED


@receiver(post_delete, sender=ReviewBackup)
def delete_review_backup_file(sender, instance, **kwargs):
    """The archive goes with its place in the list."""
    StoredFile.objects.filter(pk=instance.file_id).delete()


# ---------------------------------------------------------------------------------------------------------------------
# History of a review (PRISMA 2020 item 24c: amendments to the protocol)
# ---------------------------------------------------------------------------------------------------------------------


class ReviewEvent(models.Model):
    """
    One change to a review, for its History: who made it, when, through what and what changed (see
    services.history). Nobody edits or deletes an event; the events go with the review.
    """

    REVIEW = "review"
    PLANNING = "planning"
    SEARCH = "search"
    STUDIES = "studies"
    SELECTION = "selection"
    QUALITY = "quality"
    EXTRACTION = "extraction"
    ANALYSIS = "analysis"
    REPORTING = "reporting"
    AREAS = (
        (REVIEW, _("Review")),
        (PLANNING, _("Planning")),
        (SEARCH, _("Search")),
        (STUDIES, _("Studies")),
        (SELECTION, _("Study selection")),
        (QUALITY, _("Quality assessment")),
        (EXTRACTION, _("Data extraction")),
        (ANALYSIS, _("Data analysis")),
        (REPORTING, _("Reporting")),
    )

    ADDED = "add"
    CHANGED = "change"
    REMOVED = "remove"
    ACTIONS = (
        (ADDED, _("Added")),
        (CHANGED, _("Changed")),
        (REMOVED, _("Removed")),
    )

    WEB = "web"
    API = "api"
    CLI = "cli"
    MCP = "mcp"
    SYSTEM = "system"
    VIA = (
        (WEB, _("Web")),
        (API, _("API")),
        (CLI, _("CLI")),
        (MCP, _("MCP")),
        (SYSTEM, _("Parsifal")),  # no request: a management command, the shell
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="events")
    created_at = models.DateTimeField(_("when"), auto_now_add=True, db_index=True)
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # The actor's name then; it stays when the account goes (a deleted agent).
    actor_name = models.CharField(_("who"), max_length=150, blank=True)
    via = models.CharField(_("via"), max_length=6, choices=VIA, default=WEB)
    area = models.CharField(_("area"), max_length=10, choices=AREAS)
    action = models.CharField(_("action"), max_length=6, choices=ACTIONS)
    # What was done, without who: "Changed the exclusion criterion “Not peer reviewed”".
    summary = models.CharField(_("what"), max_length=500)
    # What the change was about: "criterion", "study", ... and its id (it may no longer exist).
    subject = models.CharField(_("subject"), max_length=30, blank=True)
    subject_id = models.BigIntegerField(null=True, blank=True)
    # Each field changed: [{"key": "description", "field": "Description", "before": "...", "after": "..."}].
    changes = models.JSONField(_("changes"), default=list, blank=True)
    # Names of what the change took with it or applied to, when there is no study to point to (studies deleted).
    items = models.JSONField(_("items"), default=list, blank=True)
    articles = models.ManyToManyField(Article, blank=True, related_name="events", verbose_name=_("studies"))
    run = models.ForeignKey(ScreeningRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    # A change to the protocol (Planning) made after the first study was imported: an amendment to report.
    amendment = models.BooleanField(_("amendment to the protocol"), default=False)

    class Meta:
        verbose_name = _("review event")
        verbose_name_plural = _("review events")
        ordering = ("-created_at", "-pk")
        indexes = (models.Index(fields=("review", "-created_at"), name="review_event_latest"),)

    def __str__(self):
        return f"{self.actor_name or '?'}: {self.summary}"
